"""JobSpy adapter for Indeed searches, including India."""

from config import (
    INDEED_COUNTRY, INDEED_LOCATION, INDEED_RESULTS_PER_SEARCH, INDEED_SEARCHES,
    MAX_POSTING_AGE_DAYS,
)
from models import Job
from sources.jobspy_common import fetch_jobs


def fetch_indeed() -> list[Job]:
    return fetch_jobs(
        "indeed", INDEED_SEARCHES, country=INDEED_COUNTRY, location=INDEED_LOCATION,
        results_per_search=INDEED_RESULTS_PER_SEARCH,
        hours_old=MAX_POSTING_AGE_DAYS * 24,
    )
