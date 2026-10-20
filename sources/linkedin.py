"""JobSpy adapter for public LinkedIn job listings."""

from dataclasses import replace

from bs4 import BeautifulSoup

from config import LINKEDIN_MAX_DETAIL_FETCHES, LINKEDIN_RESULTS_PER_SEARCH, PROFILE, Profile
from models import Job
from sources import get_public_page
from sources.enrichment import detail_text, enrich_jobs
from sources.jobspy_common import fetch_jobs, normalize_record as normalize_jobspy_record


def normalize_record(record: dict) -> Job | None:
    return normalize_jobspy_record(record, "linkedin")


def parse_detail(html: str, job: Job) -> Job:
    soup = BeautifulSoup(html, "html.parser")
    description = soup.select_one(".show-more-less-html__markup")
    if description is None:
        raise ValueError("LinkedIn public description was unavailable")
    employment = None
    for criterion in soup.select(".description__job-criteria-item"):
        heading = criterion.select_one(".description__job-criteria-subheader")
        value = criterion.select_one(".description__job-criteria-text")
        if heading and value and heading.get_text(strip=True).casefold() == "employment type":
            normalized = normalize_record({"title": job.title, "job_url": job.url, "job_type": value.get_text(strip=True)})
            employment = normalized.employment_type if normalized else None
    return replace(job, description=detail_text(description),
                   employment_type=job.employment_type or employment)


def fetch_linkedin(*, profile: Profile = PROFILE, processed_ids: set[str] | None = None) -> list[Job]:
    jobs = fetch_jobs(
        "linkedin", profile.linkedin_searches, location=profile.linkedin_location,
        results_per_search=LINKEDIN_RESULTS_PER_SEARCH, hours_old=72,
        fetch_description=False,
    )
    return enrich_jobs(
        jobs, lambda job: parse_detail(get_public_page(job.url), job),
        limit=LINKEDIN_MAX_DETAIL_FETCHES, profile=profile, processed_ids=processed_ids,
    )
