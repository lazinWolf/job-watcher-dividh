from datetime import datetime, timedelta, timezone

import pytest

from config import Profile
from evaluate import evaluate
from models import Job

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)
PROFILE = Profile()


def job(title: str, **changes) -> Job:
    fields = dict(id="linkedin:1", source="linkedin", title=title, url="https://example.com/1")
    fields.update(changes)
    return Job(**fields)


def test_sparse_backend_intern_exceeds_initial_threshold():
    assert evaluate(job("Backend Engineer Intern"), PROFILE, now=NOW).score == 70


def test_senior_mention_in_description_does_not_reject_intern():
    result = evaluate(job("Backend Engineer Intern", description="Work with senior engineers."), PROFILE, now=NOW)
    assert result.score == 70
    assert evaluate(job("Senior Backend Engineer"), PROFILE, now=NOW).score is None


def test_required_experience_rejected_but_preferred_is_not():
    assert evaluate(job("Backend Engineer", description="Minimum 5 years of experience required."), PROFILE, now=NOW).score is None
    assert evaluate(job("Backend Engineer", description="5 years of experience preferred."), PROFILE, now=NOW).score is not None


def test_go_does_not_match_prose_and_overlapping_career_terms_count_once():
    result = evaluate(job("Graduate Backend Engineer Intern", description="We go to market soon."), PROFILE, now=NOW)
    assert result.score == 70
    tagged = evaluate(job("Graduate Backend Engineer Intern", skills=("Go",)), PROFILE, now=NOW)
    assert tagged.score == 75


def test_missing_location_is_kept_but_known_mismatch_is_rejected():
    profile = Profile(allowed_locations=("Pune",))
    assert evaluate(job("Backend Intern"), profile, now=NOW).score is not None
    assert evaluate(job("Backend Intern", location="Mumbai"), profile, now=NOW).score is None


def test_old_posting_is_rejected():
    result = evaluate(job("Backend Intern", posted_at=NOW - timedelta(days=9)), PROFILE, now=NOW)
    assert result.score is None


def test_explicit_mandatory_years_in_title_is_rejected():
    assert evaluate(job("AI Engineer (3+ years mandatory)"), PROFILE, now=NOW).score is None


def test_remote_country_kept_when_only_city_preference_is_known():
    profile = Profile(allowed_locations=("Pune",))
    result = evaluate(job("Backend Intern", location="Remote only • India", workplace_type="remote"), profile, now=NOW)
    assert result.score is not None


def test_requirements_section_ends_at_company_and_role_headings():
    description = ("Requirements\nPython, SQL\nAbout the company\nWe bring 10 years of experience serving clients.\n"
                   "What you'll do\n5 years of experience across our platform.")
    assert evaluate(job("Backend Engineer Intern", description=description), PROFILE, now=NOW).score == 75
    still_required = "Requirements\nPython\nStrong communication\n3+ years of backend experience"
    assert evaluate(job("Backend Engineer", description=still_required), PROFILE, now=NOW).reasons == ("requires 3+ years",)


def test_internship_titles_with_senior_words_are_scored():
    assert evaluate(job("Backend Engineer Intern - Lead Gen Platform"), PROFILE, now=NOW).score == 70
    assert evaluate(job("Product Manager Intern"), PROFILE, now=NOW).score is not None
    assert evaluate(job("Senior Backend Engineer"), PROFILE, now=NOW).reasons == ("senior role title",)
    assert evaluate(job("Engineering Manager"), PROFILE, now=NOW).reasons == ("senior role title",)


def test_development_titles_count_only_with_technical_qualifier():
    profile = Profile(role_terms=("backend",))
    assert evaluate(job("Full Stack Development"), profile, now=NOW).reasons[0] == "related engineering role"
    assert evaluate(job("Python Development"), profile, now=NOW).reasons[0] == "related engineering role"
    assert "related engineering role" not in evaluate(job("Business Development"), profile, now=NOW).reasons


def test_remote_title_passes_location_filter_and_earns_workplace_points():
    profile = Profile(allowed_locations=("Pune",), preferred_workplaces=("remote",))
    remote = evaluate(job("Backend Developer Intern (Remote)", location="Kerala, India"), profile, now=NOW)
    assert remote.score is not None and "preferred remote work" in remote.reasons
    assert evaluate(job("Backend Developer Intern", location="Kerala, India"), profile, now=NOW).score is None
    onsite = job("Backend Developer Intern (Remote)", location="Kerala, India", workplace_type="onsite")
    assert evaluate(onsite, profile, now=NOW).score is None


def test_country_only_location_is_kept_for_manual_review():
    profile = Profile(allowed_locations=("Pune",), country_locations=("India", "IN"))
    assert evaluate(job("Backend Intern", location="India"), profile, now=NOW).score is not None
    assert evaluate(job("Backend Intern", location="IN"), profile, now=NOW).score is not None
    assert evaluate(job("Backend Intern", location="Delhi, India"), profile, now=NOW).score is None
    assert evaluate(job("Backend Intern", location="India"), Profile(allowed_locations=("Pune",)), now=NOW).score is None


@pytest.mark.parametrize("description", [
    "Selected candidates must pay a registration fee of Rs 2000.",
    "A refundable deposit is collected before onboarding.",
    "Training fees: INR 4999 (one-time).",
])
def test_payment_requests_are_rejected(description):
    assert evaluate(job("Backend Engineer Intern", description=description), PROFILE, now=NOW).reasons == ("asks for payment",)


@pytest.mark.parametrize("description", [
    "There is no registration fee for this internship.",
    "Registration fee: nil. Stipend paid monthly.",
    "We will never ask you to pay a fee.",
    "Free training is provided; the stipend is INR 10,000.",
])
def test_payment_free_postings_are_kept(description):
    assert evaluate(job("Backend Engineer Intern", description=description), PROFILE, now=NOW).score is not None


def test_linkedin_seniority_supplies_career_evidence():
    entry = evaluate(job("Backend Engineer", seniority="Entry level"), PROFILE, now=NOW)
    assert "early-career role" in entry.reasons and entry.score == 70
    assert evaluate(job("Backend Engineer", seniority="Mid-Senior level"), PROFILE, now=NOW).reasons == (
        "senior role (LinkedIn seniority)",)
    # An explicitly junior title outranks a recruiter's level label.
    assert evaluate(job("Junior Backend Engineer", seniority="Mid-Senior level"), PROFILE, now=NOW).score is not None
    experienced = Profile(career_stage="experienced", experience_years=5, max_required_years=6)
    assert evaluate(job("Backend Engineer", seniority="Mid-Senior level"), experienced, now=NOW).score is not None
