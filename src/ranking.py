"""Ranking.

rank_score = match_score (primary) + recency bonus + location bonus.
Weights are chosen so location can nudge ties but never overpower a clearly
better resume match.
"""

from __future__ import annotations

from datetime import datetime, timezone

from config import Config
from src.models import Job

# Secondary factors are small relative to the 0-100 match score.
RECENCY_MAX_BONUS = 10.0   # within the last hour
LOCATION_MAX_BONUS = 8.0   # top-priority location
REMOTE_BONUS = 3.0


def _recency_bonus(job: Job) -> float:
    if job.posted_at is None:
        return 0.0
    hours = (datetime.now(timezone.utc) - job.posted_at).total_seconds() / 3600.0
    if hours <= 0:
        return RECENCY_MAX_BONUS
    # Linear decay over 7 days (168h) down to 0.
    decayed = RECENCY_MAX_BONUS * max(0.0, 1 - hours / 168.0)
    return round(decayed, 2)


def _location_bonus(job: Job, priority: list[str]) -> float:
    if not priority:
        return 0.0
    loc = job.location.lower()
    for idx, city in enumerate(priority):
        if city.lower() in loc:
            # First city gets the max bonus; each step down loses a slice.
            step = LOCATION_MAX_BONUS / max(1, len(priority))
            return round(LOCATION_MAX_BONUS - idx * step, 2)
    return 0.0


def compute_rank_score(job: Job, config: Config) -> float:
    score = float(job.match_score)
    score += _recency_bonus(job)
    score += _location_bonus(job, config.location_priority)
    if job.work_mode == "remote":
        score += REMOTE_BONUS
    return round(score, 2)


def rank(jobs: list[Job], config: Config) -> list[Job]:
    for job in jobs:
        job.rank_score = compute_rank_score(job, config)
    return sorted(jobs, key=lambda j: j.rank_score, reverse=True)
