"""Lightweight MVP tests. Run with: python -m pytest -q  (or python tests/test_pipeline.py)

Covers: config load, normalization, SQLite dedup, resume extraction,
keyword matching, ranking, and that a second run skips previously seen jobs.
External APIs are mocked.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config  # noqa: E402
from src import database, ranking  # noqa: E402
from src.filters import apply_filters  # noqa: E402
from src.matcher import keyword_match  # noqa: E402
from src.models import build_job, infer_work_mode, parse_date  # noqa: E402
from src.resume_parser import extract_skills  # noqa: E402


def test_config_loads():
    cfg = load_config()
    assert cfg.max_job_age_days >= 0
    assert len(cfg.skills_vocabulary) > 10
    assert len(cfg.target_roles) > 5


def test_normalization():
    job = build_job(
        source="adzuna", source_id="123", title="  Python Developer ",
        company=None, location="Remote - India", url="http://x/y",
        description="<p>Build <b>APIs</b> with Python</p>", posted_at="2026-10-07T10:00:00Z",
    )
    assert job is not None
    assert job.uid == "adzuna:123"
    assert job.company == "Unknown company"
    assert "<" not in job.description  # HTML stripped
    assert job.work_mode == "remote"
    assert isinstance(job.posted_at, datetime)

    # Malformed: no title and no url -> None
    assert build_job(source="s", source_id="", title="", company="x",
                     location="", url="", description="", posted_at=None) is None


def test_infer_work_mode_and_dates():
    assert infer_work_mode("Hybrid role in Pune") == "hybrid"
    assert infer_work_mode("Work from home") == "remote"
    assert infer_work_mode("On-site, Bengaluru") == "onsite"
    assert infer_work_mode("") == "unknown"
    assert parse_date("2026-10-07").year == 2026
    assert parse_date("not a date") is None


def test_sqlite_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "jobs.db")
        database.init_db(db)
        job = build_job(source="s", source_id="1", title="Dev", company="C",
                        location="Pune", url="http://u", description="python",
                        posted_at=datetime.now(timezone.utc))
        assert database.is_seen(job.uid, db) is False
        database.mark_seen(job, db)
        assert database.is_seen(job.uid, db) is True
        database.mark_seen(job, db)  # idempotent
        assert database.count_seen(db) == 1


def test_resume_extraction():
    text = "Experienced in Python, Java, Docker and AWS. Built REST API services."
    cfg = load_config()
    skills = extract_skills(text, cfg.skills_vocabulary)
    assert "Python" in skills
    assert "Java" in skills
    assert "AWS" in skills
    assert "REST API" in skills


def test_keyword_matching():
    cfg = load_config()
    job = build_job(source="s", source_id="1", title="Backend Developer",
                    company="C", location="Bengaluru",
                    url="http://u",
                    description="We need Python, Django, PostgreSQL and Docker.",
                    posted_at=datetime.now(timezone.utc))
    resume_skills = ["Python", "Django", "Docker"]
    result = keyword_match(job, resume_skills, cfg)
    assert 0 <= result["match_score"] <= 100
    assert "Python" in result["matching_skills"]
    assert "PostgreSQL" in result["missing_skills"]
    assert result["recommendation"] in ("APPLY", "CONSIDER", "LOW PRIORITY")

    # No skills in JD -> no divide by zero
    empty = build_job(source="s", source_id="2", title="Role", company="C",
                      location="X", url="http://u2", description="generic text",
                      posted_at=datetime.now(timezone.utc))
    r2 = keyword_match(empty, resume_skills, cfg)
    assert r2["match_score"] == 0.0


def test_ranking_order():
    cfg = load_config()
    now = datetime.now(timezone.utc)
    high = build_job(source="s", source_id="h", title="Dev", company="C",
                     location="Other City", url="http://h", description="x", posted_at=now)
    high.match_score = 90
    low = build_job(source="s", source_id="l", title="Dev", company="C",
                    location="Bengaluru", url="http://l", description="x", posted_at=now)
    low.match_score = 50
    ordered = ranking.rank([low, high], cfg)
    # Higher match score must win despite worse location.
    assert ordered[0].match_score == 90


def test_filters_relevance_and_recency():
    cfg = load_config()
    now = datetime.now(timezone.utc)
    good = build_job(source="s", source_id="1", title="Software Engineer", company="C",
                     location="Pune", url="http://g", description="python", posted_at=now)
    irrelevant = build_job(source="s", source_id="2", title="Chef", company="C",
                           location="Pune", url="http://i", description="cooking", posted_at=now)
    old = build_job(source="s", source_id="3", title="Developer", company="C",
                    location="Pune", url="http://o", description="java",
                    posted_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
    out = apply_filters([good, irrelevant, old], cfg, days=1)
    uids = {j.uid for j in out}
    assert "s:1" in uids
    assert "s:2" not in uids
    assert "s:3" not in uids


def test_multi_resume_best_fit():
    """Multi-resume: a security job should prefer the security profile."""
    import tempfile
    from src.matcher import match_job_multi
    from src.resume_parser import load_resume_profiles
    cfg = load_config()

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "01-security.txt"), "w", encoding="utf-8") as fh:
            fh.write("Burp Suite Nmap Wireshark Metasploit Penetration Testing SIEM Splunk Cybersecurity")
        with open(os.path.join(tmp, "02-frontend.txt"), "w", encoding="utf-8") as fh:
            fh.write("React Next.js TypeScript HTML CSS Node.js Express")

        profiles = load_resume_profiles(resume_dir=tmp, vocabulary=cfg.skills_vocabulary)
        assert len(profiles) == 2
        # Labels derived from filenames, numeric prefix stripped.
        names = {p.name for p in profiles}
        assert "Security" in names and "Frontend" in names

        sec_job = build_job(source="s", source_id="1", title="Security Engineer", company="C",
                            location="Pune", url="http://u1",
                            description="Penetration Testing with Burp Suite, Nmap, Wireshark, SIEM, Splunk.",
                            posted_at=datetime.now(timezone.utc))
        match_job_multi(sec_job, profiles, cfg)
        assert sec_job.matched_resume == "Security", f"got {sec_job.matched_resume}"
        assert sec_job.match_score > 0


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
