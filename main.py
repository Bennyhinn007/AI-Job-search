"""AI Job Search - pipeline entry point.

Usage:
    python main.py                 Full run (fetch, match, rank, email, persist)
    python main.py --dry-run       Preview digest; never sends email; no creds needed
    python main.py --days 7        Widen the posting window to 7 days
    python main.py --limit 10      Max jobs in the digest
    python main.py --min-score 60  Only include jobs at/above this match score
    python main.py --fetch-only    Fetch + filter + show counts; stop before matching
    python main.py --check         Print a secret-safe config summary and exit

Flags can be combined, e.g. python main.py --dry-run --days 7 --min-score 70
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import describe, load_config
from src import database, filters, ranking
from src.email_sender import send_digest
from src.job_fetcher import fetch_all
from src.matcher import match_job_multi
from src.resume_parser import ResumeNotFoundError, load_resume_profiles


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AI-powered job discovery and resume matching.")
    p.add_argument("--dry-run", action="store_true", help="Preview digest; do not send email.")
    p.add_argument("--days", type=int, default=None, help="Posting age window in days (e.g. 1 or 7).")
    p.add_argument("--limit", type=int, default=None, help="Max jobs in the digest.")
    p.add_argument("--min-score", type=int, default=None, help="Minimum match score to include.")
    p.add_argument("--fetch-only", action="store_true", help="Fetch + filter only, then stop.")
    p.add_argument("--check", action="store_true", help="Print config summary and exit.")
    return p


def _make_stdout_utf8() -> None:
    """Best-effort: let the console print Unicode (e.g. emoji) on Windows cp1252."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    _make_stdout_utf8()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    config = load_config()

    # Resolve effective settings (CLI overrides config).
    days = args.days if args.days is not None else config.max_job_age_days
    limit = args.limit if args.limit is not None else config.max_email_jobs
    min_score = args.min_score if args.min_score is not None else config.min_match_score

    if args.check:
        print(describe(config))
        return 0

    database.init_db()

    # 1. Fetch
    print(f"Fetching jobs (last {days} day(s))...")
    jobs = fetch_all(config, days)
    print(f"  fetched: {len(jobs)}")

    # 2. Filter (relevance + recency)
    jobs = filters.apply_filters(jobs, config, days)
    print(f"  relevant & recent: {len(jobs)}")

    # 3. Deduplicate against SQLite (also drop in-run URL/uid duplicates)
    seen_uids: set[str] = set()
    fresh = []
    for job in jobs:
        if job.uid in seen_uids:
            continue
        seen_uids.add(job.uid)
        if not database.is_seen(job.uid):
            fresh.append(job)
    jobs = fresh
    print(f"  new (not seen before): {len(jobs)}")

    if args.fetch_only:
        for job in jobs[:limit]:
            print(f"    - [{job.source}] {job.title} @ {job.company} ({job.location})")
        return 0

    if not jobs:
        print("No new jobs to process.")
        send_digest([], config, dry_run=args.dry_run)
        return 0

    # 4. Load resume profiles (multi-resume: all files in resume/)
    try:
        profiles = load_resume_profiles(vocabulary=config.skills_vocabulary)
    except ResumeNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"  resume profiles loaded: {len(profiles)} "
          f"({', '.join(p.name for p in profiles)})")

    # 5. Match each job against the best-fitting resume profile
    for job in jobs:
        try:
            match_job_multi(job, profiles, config)
        except Exception as exc:  # never let one job kill the run
            logging.getLogger("main").warning("Match failed for a job: %s", exc)

    # 6. Rank
    jobs = ranking.rank(jobs, config)

    # 7. Apply score threshold + limit
    qualified = [j for j in jobs if j.match_score >= min_score]
    if not qualified:
        print(f"No jobs met the minimum match score of {min_score}.")
        # Still send/preview an empty digest for consistency.
        send_digest([], config, dry_run=args.dry_run)
        return 0
    digest_jobs = qualified[:limit]
    print(f"  qualifying (score >= {min_score}): {len(qualified)}; sending top {len(digest_jobs)}")

    # 8. Send digest
    sent_ok = send_digest(digest_jobs, config, dry_run=args.dry_run)

    # 9. Persist — only mark seen after a successful send (or in dry-run skip persist)
    if sent_ok and not args.dry_run:
        for job in digest_jobs:
            database.mark_seen(job)
        print(f"  marked {len(digest_jobs)} jobs as seen.")
    elif args.dry_run:
        print("  dry-run: jobs NOT marked as seen (so a real run can still send them).")
    else:
        print("  email failed: jobs NOT marked as seen; they will be retried next run.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
