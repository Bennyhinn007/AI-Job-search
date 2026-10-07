"""Normalized Job model and helpers.

Every job source converts its raw payload into a Job via build_job(), so the
rest of the pipeline is source-agnostic. Normalization is defensive: missing
or malformed fields degrade to safe defaults rather than raising.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove HTML tags and unescape entities. Never executes content."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def parse_date(value) -> datetime | None:
    """Best-effort parse of common date formats into a tz-aware UTC datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None

    raw = value.strip()
    # ISO 8601, possibly with trailing Z
    candidate = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def infer_work_mode(*texts: str) -> str:
    """Infer remote / hybrid / onsite / unknown from any provided text."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return "unknown"
    if "hybrid" in blob:
        return "hybrid"
    if "remote" in blob or "work from home" in blob or "wfh" in blob:
        return "remote"
    if any(w in blob for w in ("on-site", "onsite", "on site", "in office", "in-office")):
        return "onsite"
    return "unknown"


@dataclass
class Job:
    uid: str
    title: str
    company: str
    location: str
    work_mode: str
    posted_at: datetime | None
    url: str
    description: str
    source: str

    # Runtime matching fields (populated later in the pipeline)
    match_score: float = 0.0
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    reason: str = ""
    recommendation: str = ""
    rank_score: float = 0.0
    matched_resume: str = ""  # which resume profile scored best for this job

    def to_dict(self) -> dict:
        d = asdict(self)
        d["posted_at"] = self.posted_at.isoformat() if self.posted_at else None
        return d


def _clean(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip() or default


def build_job(
    *,
    source: str,
    source_id,
    title,
    company,
    location,
    url,
    description,
    posted_at,
    work_mode: str | None = None,
) -> Job | None:
    """Build a normalized Job from raw source fields.

    Returns None if the job is too malformed to be useful (no title and no url),
    so the caller can skip it and continue processing others.
    """
    try:
        title_c = _clean(title)
        url_c = _clean(url)
        if not title_c and not url_c:
            return None

        description_c = strip_html(_clean(description))
        location_c = _clean(location, "Unspecified")

        # Stable UID: source:id, falling back to source:url.
        sid = _clean(source_id)
        uid = f"{source}:{sid}" if sid else f"{source}:{url_c}"

        mode = work_mode or infer_work_mode(location_c, title_c, description_c)

        return Job(
            uid=uid,
            title=title_c or "Untitled role",
            company=_clean(company, "Unknown company"),
            location=location_c,
            work_mode=mode,
            posted_at=parse_date(posted_at),
            url=url_c,
            description=description_c,
            source=source,
        )
    except Exception:
        # One malformed job must never crash the pipeline.
        return None
