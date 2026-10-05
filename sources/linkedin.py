"""JobSpy adapter for public LinkedIn job listings."""

from config import LINKEDIN_LOCATION, LINKEDIN_RESULTS_PER_SEARCH, LINKEDIN_SEARCHES
from models import Job
from sources.jobspy_common import fetch_jobs, normalize_record as normalize_jobspy_record


def normalize_record(record: dict) -> Job | None:
    return normalize_jobspy_record(record, "linkedin")


def fetch_linkedin() -> list[Job]:
    return fetch_jobs(
        "linkedin", LINKEDIN_SEARCHES, location=LINKEDIN_LOCATION,
        results_per_search=LINKEDIN_RESULTS_PER_SEARCH, hours_old=72,
        fetch_description=False,
    )
