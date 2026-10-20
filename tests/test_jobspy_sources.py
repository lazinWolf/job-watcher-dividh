import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import jobspy
import pandas as pd
import pytest

import main
from evaluate import evaluate
from profiles import Profile
from sources import indeed, linkedin, naukri
from sources.jobspy_common import fetch_jobs, normalize_record

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
PROFILE = Profile()
FIXTURES = json.loads((Path(__file__).parent / "fixtures/jobspy_listings.json").read_text())


def test_live_naukri_fields_reject_senior_experience_despite_generic_title():
    job = normalize_record(FIXTURES["naukri"][0], "naukri")
    assert job.id == "naukri:051026906685"
    assert job.experience_min_years == 8
    assert job.skills and "agile" in job.skills
    assert job.workplace_type == "onsite"
    assert job.employment_type == "fulltime"
    assert job.description and job.location == "Bengaluru, India"
    assert evaluate(job, PROFILE, now=NOW).reasons == ("requires 8+ years",)


def test_indeed_identity_and_sparse_fields_from_live_sample():
    record = FIXTURES["indeed"][0]
    job = normalize_record(record, "indeed")
    assert job.id == "indeed:4844c56c8c1d9d04"
    assert job.source == "indeed" and job.description
    assert job.posted_at == NOW
    assert job.compensation is None and job.skills == ()
    assert job.workplace_type is None  # false remote is not proof of onsite
    without_id = dict(record, id=None, job_url=record["job_url"] + "&utm_source=test")
    assert normalize_record(without_id, "indeed").id == job.id


def test_pay_skills_and_hybrid_are_preserved():
    job = normalize_record(dict(FIXTURES["naukri"][0],
        min_amount=600000, max_amount=900000, currency="INR", interval="yearly",
        experience_range="0-2 Yrs", skills="Python, Docker, Python",
        work_from_home_type="Hybrid", is_remote=False,
        description="Minimum 0–2 years of experience required. Python and Docker."), "naukri")
    assert job.compensation == "INR 600,000–900,000 (yearly)"
    assert job.skills == ("Python", "Docker")
    assert job.experience_min_years == 0 and job.workplace_type == "hybrid"
    assert evaluate(job, PROFILE, now=NOW).score >= 60


@pytest.mark.parametrize("experience", [None, float("nan"), "Not disclosed", "Fresher", "2 months", "2-3", "8-2 Yrs"])
def test_unknown_experience_is_not_assumed_zero(experience):
    job = normalize_record(dict(FIXTURES["naukri"][0], experience_range=experience), "naukri")
    assert job.experience_min_years is None


@pytest.mark.parametrize("job_type", ["contract", "parttime", "temporary"])
def test_non_selected_employment_types_are_rejected(job_type):
    job = normalize_record(dict(FIXTURES["indeed"][0], job_type=job_type), "indeed")
    assert job.employment_type == job_type
    assert evaluate(job, PROFILE, now=NOW).score is None
    assert "outside selected job types" in evaluate(job, PROFILE, now=NOW).reasons[0]


def test_nan_and_malformed_records_do_not_become_fake_jobs():
    assert normalize_record({"title": float("nan"), "job_url": "https://example.com"}, "indeed") is None
    assert normalize_record({"title": "Backend Developer", "job_url": "javascript:alert(1)"}, "naukri") is None
    assert normalize_record(FIXTURES["naukri"][0], "indeed") is None
    record = dict(FIXTURES["naukri"][0], company=pd.NA, skills=pd.NA,
                  date_posted=pd.NaT, min_amount=float("nan"), max_amount=float("nan"))
    job = normalize_record(record, "naukri")
    assert job.company is None and job.posted_at is None
    assert job.skills == () and job.compensation is None


def test_search_overlap_merges_descriptions_and_uses_bounded_options(monkeypatch):
    calls = []
    def scrape(**options):
        calls.append(options)
        record = dict(FIXTURES["naukri"][0])
        if len(calls) == 1:
            record["description"] = None
        return pd.DataFrame([record])
    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    jobs = fetch_jobs("naukri", ("python", "backend"), location="Pune",
                      results_per_search=5, hours_old=168, fetch_description=True)
    assert len(jobs) == 1 and jobs[0].description
    assert all(call["site_name"] == ["naukri"] and call["results_wanted"] == 5
               and call["fetch_description"] is True and call["location"] == "Pune"
               and call["hours_old"] == 168 for call in calls)
    assert all("linkedin_fetch_description" not in call for call in calls)


def test_logged_block_without_exception_is_a_source_failure(monkeypatch):
    logger = logging.getLogger("JobSpy:Naukri")
    handlers_before = list(logger.handlers)
    def scrape(**_):
        logger.error("Naukri rejected the request token (406)")
        return pd.DataFrame()
    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    with pytest.raises(RuntimeError, match="All naukri queries failed.*406"):
        fetch_jobs("naukri", ("python",))
    assert logger.handlers == handlers_before


def test_successful_empty_search_is_not_a_source_failure(monkeypatch):
    monkeypatch.setattr(jobspy, "scrape_jobs", lambda **_: pd.DataFrame())
    assert fetch_jobs("indeed", ("unusual title",)) == []


def test_failed_query_does_not_discard_other_results(monkeypatch, caplog):
    def scrape(**options):
        if options["search_term"] == "bad":
            raise RuntimeError("unavailable")
        return pd.DataFrame(FIXTURES["indeed"])
    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    jobs = fetch_jobs("indeed", ("bad", "good"))
    assert len(jobs) == 2
    assert "indeed query failed: bad" in caplog.text


def test_adapters_use_current_api_and_preserve_linkedin_ids(monkeypatch):
    calls = []
    def scrape(**options):
        calls.append(options)
        return pd.DataFrame()
    monkeypatch.setattr(jobspy, "scrape_jobs", scrape)
    linkedin.fetch_linkedin()
    indeed.fetch_indeed()
    naukri.fetch_naukri()
    assert all("linkedin_fetch_description" not in call for call in calls)
    assert all(call["fetch_description"] for call in calls if call["site_name"] == ["naukri"])
    assert all(call["country_indeed"] == "India" for call in calls if call["site_name"] == ["indeed"])
    record = {"id": "li-42", "title": "Backend Intern", "job_url": "https://www.linkedin.com/jobs/view/42?trk=abc"}
    assert linkedin.normalize_record(record).id == "linkedin:42"


def test_new_sources_flow_through_pipeline_without_state_or_delivery(tmp_path):
    path = tmp_path / "seen.json"
    fetchers = {source: lambda source=source: [normalize_record(record, source) for record in FIXTURES[source]]
                for source in ("indeed", "naukri")}
    status, summary = main.run(path, dry_run=True, fetchers=fetchers, sender=lambda *_: pytest.fail("must not send"))
    assert status == 0 and summary.sources_ok == 2 and summary.collected == 4
    assert summary.rejected >= 2 and not path.exists()
    assert "indeed" in main.FETCHERS and "naukri" in main.FETCHERS
