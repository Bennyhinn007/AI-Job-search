"""Job sources behind a common interface.

Each JobSource subclass fetches from one provider and normalizes results into
Job objects. Failures are contained: a source that errors logs a warning and
returns an empty list so the rest of the pipeline continues.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from config import Config
from src.models import Job, build_job

log = logging.getLogger("job_fetcher")

HTTP_TIMEOUT = 15  # seconds


class JobSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, config: Config, days: int, keywords: str) -> list[Job]:
        """Return normalized Job objects. Must not raise on network errors."""
        raise NotImplementedError

    def available(self, config: Config) -> bool:  # noqa: D401
        """Whether this source has what it needs to run."""
        return True


class AdzunaSource(JobSource):
    name = "adzuna"
    BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"

    def available(self, config: Config) -> bool:
        return config.has_adzuna

    def fetch(self, config: Config, days: int, keywords: str) -> list[Job]:
        if not self.available(config):
            log.info("Adzuna skipped: no API credentials configured.")
            return []

        params = {
            "app_id": config.adzuna_app_id,
            "app_key": config.adzuna_app_key,
            "what_or": keywords,
            "max_days_old": days,
            "results_per_page": 50,
            "content-type": "application/json",
        }
        url = self.BASE.format(country=config.adzuna_country)
        try:
            resp = requests.get(url, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Adzuna fetch failed: %s", exc)
            return []

        jobs: list[Job] = []
        for raw in data.get("results", []):
            try:
                loc = (raw.get("location") or {}).get("display_name", "")
                category = (raw.get("category") or {}).get("label", "")
                # Adzuna truncates the description server-side; fold in the
                # title and category so skill detection has more signal.
                desc = raw.get("description") or ""
                enriched = f"{raw.get('title', '')}. {category}. {desc}"
                job = build_job(
                    source=self.name,
                    source_id=raw.get("id"),
                    title=raw.get("title"),
                    company=(raw.get("company") or {}).get("display_name"),
                    location=loc,
                    url=raw.get("redirect_url"),
                    description=enriched,
                    posted_at=raw.get("created"),
                )
                if job:
                    jobs.append(job)
            except Exception as exc:  # one bad record must not kill the batch
                log.debug("Skipping malformed Adzuna record: %s", exc)
        log.info("Adzuna returned %d jobs.", len(jobs))
        return jobs


class RemotiveSource(JobSource):
    name = "remotive"
    BASE = "https://remotive.com/api/remote-jobs"

    def fetch(self, config: Config, days: int, keywords: str) -> list[Job]:
        params = {"search": keywords, "limit": 50}
        try:
            resp = requests.get(self.BASE, params=params, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.warning("Remotive fetch failed: %s", exc)
            return []

        jobs: list[Job] = []
        for raw in data.get("jobs", []):
            try:
                job = build_job(
                    source=self.name,
                    source_id=raw.get("id"),
                    title=raw.get("title"),
                    company=raw.get("company_name"),
                    location=raw.get("candidate_required_location") or "Remote",
                    url=raw.get("url"),
                    description=raw.get("description"),
                    posted_at=raw.get("publication_date"),
                    work_mode="remote",
                )
                if job:
                    jobs.append(job)
            except Exception as exc:
                log.debug("Skipping malformed Remotive record: %s", exc)
        log.info("Remotive returned %d jobs.", len(jobs))
        return jobs


# Registry: add new sources here and they flow through the whole pipeline.
ALL_SOURCES: list[JobSource] = [AdzunaSource(), RemotiveSource()]


def default_keywords(config: Config) -> str:
    """A compact keyword string for source queries (first few target roles)."""
    core = ["software engineer", "developer", "devops", "cybersecurity",
            "data engineer", "cloud engineer"]
    return " ".join(core)


def fetch_all(config: Config, days: int, sources: list[JobSource] | None = None) -> list[Job]:
    """Fetch from every source, tolerating individual source failures."""
    sources = sources if sources is not None else ALL_SOURCES
    keywords = default_keywords(config)
    collected: list[Job] = []
    succeeded = 0
    for src in sources:
        try:
            batch = src.fetch(config, days, keywords)
            collected.extend(batch)
            succeeded += 1
        except Exception as exc:  # safety net; sources already guard internally
            log.warning("Source %s crashed unexpectedly: %s", src.name, exc)
    if succeeded == 0:
        log.error("All job sources failed. Check your network/credentials.")
    return collected
