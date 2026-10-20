"""Shared normalization and bounded searches for JobSpy sources."""

import logging
import math
import re
from urllib.parse import parse_qs, urlsplit

from models import Job, canonical_url, job_id, merge_jobs, parse_posted_at

LOGGER = logging.getLogger(__name__)
SOURCE_LOGGERS = {
    "linkedin": "JobSpy:LinkedIn", "indeed": "JobSpy:Indeed", "naukri": "JobSpy:Naukri",
}


def _value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text.casefold() in {"", "nan", "nat", "none", "<na>"} else text


def _source_id(record: dict, source: str, url: str) -> str | None:
    if source == "linkedin":
        # Preserve existing LinkedIn state IDs when upgrading the adapter.
        match = re.search(r"linkedin\.com/jobs/view/(\d+)", url)
        return match.group(1) if match else _value(record.get("id"))
    if source == "indeed":
        key = parse_qs(urlsplit(url).query).get("jk", [None])[0]
        return key or (_value(record.get("id")) or "").removeprefix("in-") or None
    key = _value(record.get("id"))
    if key:
        return key.removeprefix("nk-")
    match = re.search(r"(?:-|/)(\d+)$", urlsplit(url).path)
    return match.group(1) if match else None


def _employment_type(value: object) -> str | None:
    text = (_value(value) or "").casefold()
    types = {name for name, pattern in {
        "internship": r"\bintern(?:ship)?\b",
        "fulltime": r"\bfull[ _-]?time\b",
        "parttime": r"\bpart[ _-]?time\b",
        "contract": r"\bcontract\b",
        "temporary": r"\btemporary\b",
    }.items() if re.search(pattern, text)}
    return types.pop() if len(types) == 1 else None


def _experience(value: object) -> int | None:
    # Only accept explicit years; do not infer experience from a job title.
    text = _value(value) or ""
    match = re.fullmatch(r"\s*(\d{1,2})(?:\s*[-–]\s*\d{1,2}|\s*\+)?\s*(?:yrs?|years?)\s*", text, re.I)
    if not match:
        return None
    numbers = re.findall(r"\d+", text)
    if len(numbers) == 2 and int(numbers[1]) < int(numbers[0]):
        return None
    return int(match.group(1))


def _compensation(record: dict) -> str | None:
    def amount(key: str) -> str | None:
        try:
            number = float(record.get(key))
        except (TypeError, ValueError):
            return None
        return f"{number:,.2f}".rstrip("0").rstrip(".") if math.isfinite(number) and number >= 0 else None

    low, high = amount("min_amount"), amount("max_amount")
    if low is None and high is None:
        return None
    if low == high:
        pay = low
    elif low is not None and high is not None:
        pay = f"{low}–{high}"
    elif low is not None:
        pay = f"from {low}"
    else:
        pay = f"up to {high}"
    currency = _value(record.get("currency"))
    interval = _value(record.get("interval"))
    return " ".join(filter(None, (currency, pay, f"({interval})" if interval else None)))


def normalize_record(record: dict, source: str) -> Job | None:
    if source not in SOURCE_LOGGERS:
        raise ValueError(f"Unsupported JobSpy source: {source}")
    if _value(record.get("site")) not in (None, source):
        return None
    title, raw_url = _value(record.get("title")), _value(record.get("job_url"))
    if not title or not raw_url:
        return None
    try:
        url = canonical_url(raw_url)
    except ValueError:
        return None
    location = ", ".join(filter(None, (_value(record.get("city")), _value(record.get("state")), _value(record.get("country"))))) or _value(record.get("location"))
    work_mode = (_value(record.get("work_from_home_type")) or "").casefold()
    # A false remote flag alone cannot distinguish hybrid and onsite work.
    workplace = None
    if "hybrid" in work_mode:
        workplace = "hybrid"
    elif "remote" in work_mode or str(record.get("is_remote")).casefold() in {"true", "1"}:
        workplace = "remote"
    elif work_mode in {"work from office", "onsite", "on-site", "on site"}:
        workplace = "onsite"
    raw_skills = record.get("skills")
    if isinstance(raw_skills, (list, tuple)):
        skills = tuple(filter(None, (_value(skill) for skill in raw_skills)))
    else:
        skills = tuple(skill.strip() for skill in (_value(raw_skills) or "").split(",") if skill.strip())
    return Job(
        id=job_id(source, url, _source_id(record, source, url)), source=source,
        title=title, url=url, company=_value(record.get("company")), location=location,
        compensation=_compensation(record), description=_value(record.get("description")),
        posted_at=parse_posted_at(_value(record.get("date_posted"))),
        employment_type=_employment_type(record.get("job_type")), workplace_type=workplace,
        experience_min_years=_experience(record.get("experience_range")),
        skills=tuple(dict.fromkeys(skills)),
        seniority=_value(record.get("job_level")),
    )


class _QueryErrors(logging.Handler):
    """JobSpy sometimes logs a request failure and returns an empty dataframe."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def fetch_jobs(
    source: str, searches: tuple[str, ...], *, location: str = "",
    country: str = "India", results_per_search: int = 20,
    hours_old: int = 72, fetch_description: bool = False,
) -> list[Job]:
    if source not in SOURCE_LOGGERS or not searches or results_per_search < 1:
        raise ValueError("Specify a supported source, searches, and a positive result limit")
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError("Install requirements.txt to enable JobSpy collectors") from exc
    jobs: dict[str, Job] = {}
    failures: list[str] = []
    successful_queries = 0
    for term in searches:
        errors = _QueryErrors()
        upstream_logger = logging.getLogger(SOURCE_LOGGERS[source])
        upstream_logger.addHandler(errors)
        try:
            options = dict(
                site_name=[source], search_term=term, results_wanted=results_per_search,
                hours_old=hours_old, fetch_description=fetch_description, verbose=1,
            )
            if location:
                options["location"] = location
            if source == "indeed":
                options["country_indeed"] = country
            records = scrape_jobs(**options).to_dict("records")
            parsed = [job for record in records if (job := normalize_record(record, source))]
            LOGGER.info("%s query %r: %d returned, %d parsed, result limit %d%s", source,
                        term, len(records), len(parsed), results_per_search,
                        "; cap reached, more results may exist" if len(records) >= results_per_search else "")
            if records and not parsed:
                errors.messages.append("results did not contain valid job titles and URLs")
            if errors.messages:
                failures.append(f"{term}: " + "; ".join(errors.messages))
            else:
                successful_queries += 1
            for job in parsed:
                jobs[job.id] = merge_jobs(jobs[job.id], job) if job.id in jobs else job
        except Exception as exc:
            failures.append(f"{term}: {type(exc).__name__}: {exc}")
        finally:
            upstream_logger.removeHandler(errors)
            errors.close()
    for failure in failures:
        LOGGER.warning("%s query failed: %s", source, failure)
    if not jobs and not successful_queries:
        raise RuntimeError(f"All {source} queries failed; " + "; ".join(failures))
    result = list(jobs.values())
    LOGGER.info("%s: %d unique jobs; descriptions %d/%d; %d failed queries",
                source, len(result), sum(bool(job.description) for job in result),
                len(result), len(failures))
    return result
