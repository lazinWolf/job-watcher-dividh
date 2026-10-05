"""JobSpy adapter for Naukri, with bounded description enrichment."""

from config import (
    MAX_POSTING_AGE_DAYS, NAUKRI_LOCATION, NAUKRI_RESULTS_PER_SEARCH, NAUKRI_SEARCHES,
)
from models import Job
from sources.jobspy_common import fetch_jobs


def fetch_naukri() -> list[Job]:
    return fetch_jobs(
        "naukri", NAUKRI_SEARCHES, location=NAUKRI_LOCATION,
        results_per_search=NAUKRI_RESULTS_PER_SEARCH,
        hours_old=MAX_POSTING_AGE_DAYS * 24, fetch_description=True,
    )
