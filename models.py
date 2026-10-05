"""Small shared types and source-independent normalization helpers."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class Job:
    id: str
    source: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    compensation: str | None = None
    description: str | None = None
    posted_at: datetime | None = None
    employment_type: str | None = None  # internship, fulltime, contract, parttime, temporary, or unknown
    workplace_type: str | None = None  # remote, hybrid, onsite, or unknown
    experience_min_years: int | None = None
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evaluation:
    score: int | None
    reasons: tuple[str, ...] = ()


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Job URL must be absolute HTTP(S)")
    query = urlencode([
        (key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"trk", "trackingid", "ref", "refid", "source"}
    ])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", query, ""))


def job_id(source: str, url: str, source_id: str | None = None) -> str:
    if source_id and source_id.strip():
        return f"{source}:{source_id.strip()}"
    return f"{source}:{hashlib.sha256((source + ':' + canonical_url(url)).encode()).hexdigest()}"


def parse_posted_at(value: object, now: datetime | None = None) -> datetime | None:
    """Parse common ISO and English relative dates; unknown stays unknown."""
    now = now or datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in {"nan", "nat", "none", "unknown"}:
        return None
    if text in {"today", "just now", "now", "few seconds ago"}:
        return now
    if text == "yesterday":
        return now - timedelta(days=1)
    match = re.search(r"\b(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago\b", text)
    if match:
        amount = int(match.group(1))
        unit_days = {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}
        return now - timedelta(days=amount * unit_days[match.group(2)])
    try:
        parsed = datetime.fromisoformat(text.replace("z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def merge_jobs(existing: Job, incoming: Job) -> Job:
    """Keep richer fields when overlapping searches find the same source ID."""
    if existing.id != incoming.id:
        raise ValueError("Cannot merge different jobs")
    values = {}
    for name in Job.__dataclass_fields__:
        left, right = getattr(existing, name), getattr(incoming, name)
        if name in {"id", "source"}:
            values[name] = left
        elif name == "skills":
            values[name] = tuple(dict.fromkeys((*left, *right)))
        elif name == "description":
            values[name] = max((left, right), key=lambda v: len(v or ""))
        else:
            values[name] = left if left not in (None, "") else right
    return Job(**values)
