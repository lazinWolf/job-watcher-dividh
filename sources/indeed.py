"""JobSpy adapter for Indeed searches, including India."""

from config import (
    INDEED_COUNTRY_OVERRIDE, INDEED_LOCATION_OVERRIDE, INDEED_RESULTS_PER_SEARCH,
    MAX_POSTING_AGE_DAYS, PROFILE, Profile,
)
from models import Job
from sources.jobspy_common import fetch_jobs


def fetch_indeed(*, profile: Profile = PROFILE) -> list[Job]:
    return fetch_jobs(
        "indeed", profile.indeed_searches,
        country=INDEED_COUNTRY_OVERRIDE or profile.indeed_country,
        location=INDEED_LOCATION_OVERRIDE or profile.indeed_location,
        results_per_search=INDEED_RESULTS_PER_SEARCH,
        hours_old=MAX_POSTING_AGE_DAYS * 24,
    )
