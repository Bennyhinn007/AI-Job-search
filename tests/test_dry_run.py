"""End-to-end dry-run test with mocked sources + mocked SMTP.

Verifies the full pipeline renders a digest and that a second run skips
previously seen jobs (dedup). Run with: python tests/test_dry_run.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config  # noqa: E402
from src import database  # noqa: E402
from src.job_fetcher import JobSource  # noqa: E402
from src.models import build_job  # noqa: E402


class FakeSource(JobSource):
    name = "fake"

    def fetch(self, config, days, keywords):
        now = datetime.now(timezone.utc)
        return [
            build_job(source="fake", source_id="1", title="Python Developer",
                      company="Acme", location="Bengaluru", url="http://a/1",
                      description="Python Django Docker AWS REST API", posted_at=now),
            build_job(source="fake", source_id="2", title="Security Engineer",
                      company="SecCo", location="Remote", url="http://a/2",
                      description="Python Nmap Burp Suite SIEM", posted_at=now),
        ]


def test_full_dry_run_and_dedup():
    cfg = load_config()

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "jobs.db")
        database.init_db(db)

        resume = os.path.join(tmp, "resume.txt")
        with open(resume, "w", encoding="utf-8") as fh:
            fh.write("Python developer with Django, Docker, AWS and REST API experience.")

        # Simulate the pipeline's core manually so we can inject the temp DB + resume.
        from src.filters import apply_filters
        from src.matcher import match_job_multi
        from src import ranking
        from src.resume_parser import load_resume_profiles
        from src.email_sender import render_text

        jobs = FakeSource().fetch(cfg, 1, "")
        jobs = apply_filters(jobs, cfg, 1)

        # Load the temp resume as a profile (multi-resume path).
        profiles = load_resume_profiles(resume_dir=tmp, vocabulary=cfg.skills_vocabulary)
        assert len(profiles) >= 1

        # First run: both jobs are new
        new_first = [j for j in jobs if not database.is_seen(j.uid, db)]
        assert len(new_first) == 2

        for job in new_first:
            match_job_multi(job, profiles, cfg)
        new_first = ranking.rank(new_first, cfg)
        digest = render_text(new_first)
        assert "NEW JOB OPPORTUNITIES" in digest
        assert "Resume Match" in digest
        assert any(j.matched_resume for j in new_first), "matched_resume not set"

        # Mark them seen (simulating a successful send)
        for job in new_first:
            database.mark_seen(job, db)

        # Second run: same jobs -> none new
        new_second = [j for j in FakeSource().fetch(cfg, 1, "") if not database.is_seen(j.uid, db)]
        assert len(new_second) == 0, "Dedup failed: previously seen jobs returned again."

        print("PASS test_full_dry_run_and_dedup")


def test_smtp_not_called_in_dry_run():
    cfg = load_config()
    jobs = FakeSource().fetch(cfg, 1, "")
    from src.email_sender import send_digest
    with mock.patch("smtplib.SMTP_SSL") as smtp:
        ok = send_digest(jobs, cfg, dry_run=True)
        assert ok is True
        smtp.assert_not_called()
    print("PASS test_smtp_not_called_in_dry_run")


if __name__ == "__main__":
    test_full_dry_run_and_dedup()
    test_smtp_not_called_in_dry_run()
    print("\nAll dry-run tests passed.")
