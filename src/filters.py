"""Filtering: relevance (role match) and recency (posting age).

Kept pure (no I/O) so it is trivially testable. Matching is case-insensitive
and intentionally lenient to avoid dropping legitimate engineering roles.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import Config
from src.models import Job


def is_relevant(job: Job, target_roles: list[str]) -> bool:
    """True if the title or description mentions any target role keyword."""
    haystack = f"{job.title} {job.description}".lower()
    return any(role.lower() in haystack for role in target_roles)


def is_recent(job: Job, days: int, keep_unknown_dates: bool = True) -> bool:
    """True if posted within `days`. Jobs with unknown dates are kept by default."""
    if job.posted_at is None:
        return keep_unknown_dates
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return job.posted_at >= cutoff


def apply_filters(jobs: list[Job], config: Config, days: int) -> list[Job]:
    """Return jobs that are both relevant and recent."""
    out: list[Job] = []
    for job in jobs:
        try:
            if is_relevant(job, config.target_roles) and is_recent(job, days):
                out.append(job)
        except Exception:
            # Skip a single bad job rather than failing the whole filter pass.
            continue
    return out
