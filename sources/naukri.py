"""JobSpy adapter for Naukri, with bounded description enrichment."""

from config import (
    MAX_POSTING_AGE_DAYS, NAUKRI_LOCATION_OVERRIDE, NAUKRI_RESULTS_PER_SEARCH, PROFILE, Profile,
)
from models import Job
from sources.jobspy_common import fetch_jobs


def fetch_naukri(*, profile: Profile = PROFILE) -> list[Job]:
    return fetch_jobs(
        "naukri", profile.naukri_searches, location=NAUKRI_LOCATION_OVERRIDE or profile.naukri_location,
        results_per_search=NAUKRI_RESULTS_PER_SEARCH,
        hours_old=MAX_POSTING_AGE_DAYS * 24, fetch_description=True,
    )
