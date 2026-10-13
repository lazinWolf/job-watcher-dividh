from datetime import datetime, timezone
from pathlib import Path

from models import merge_jobs
from sources.internshala import parse_cards as parse_internshala
from sources.linkedin import normalize_record
from sources.wellfound import parse_cards as parse_wellfound

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_internshala_card_from_observed_markup():
    html = (Path(__file__).parent / "fixtures/internshala_card.html").read_text()
    job, = parse_internshala(html, "https://internshala.com/internships/software-development-internship/", now=NOW)
    assert job.id == "internshala:3290001"
    assert job.url == "https://internshala.com/internship/detail/backend-engineer-example"
    assert job.title == "Backend Engineer"
    assert job.location == "Work from home"
    assert job.workplace_type == "remote"
    assert job.posted_at == datetime(2026, 9, 26, tzinfo=timezone.utc)
    assert job.skills == ("Python", "Go")


def test_linkedin_normalizes_stable_id_and_missing_fields():
    job = normalize_record({
        "title": "Software Engineer Intern", "company": "Example",
        "job_url": "https://www.linkedin.com/jobs/view/4123456789/?trk=abc",
        "date_posted": "2026-09-28", "is_remote": True,
    })
    assert job and job.id == "linkedin:4123456789"
    assert job.url == "https://www.linkedin.com/jobs/view/4123456789"
    assert job.workplace_type == "remote"
    assert job.posted_at == NOW


def test_overlap_keeps_richer_listing():
    first = normalize_record({"title": "Backend Intern", "job_url": "https://www.linkedin.com/jobs/view/42"})
    second = normalize_record({"title": "Backend Intern", "job_url": "https://www.linkedin.com/jobs/view/42", "company": "Example", "description": "Python APIs"})
    combined = merge_jobs(first, second)
    assert combined.company == "Example"
    assert combined.description == "Python APIs"


def test_wellfound_structured_public_listing():
    html = '''<script type="application/ld+json">{
      "@type":"JobPosting", "title":"Junior Software Engineer",
      "url":"https://wellfound.com/jobs/4760728-junior-software-engineer",
      "datePosted":"2026-09-27", "employmentType":"FULL_TIME",
      "hiringOrganization":{"name":"Example"},
      "jobLocation":{"address":{"addressLocality":"Pune","addressCountry":"India"}}
    }</script>'''
    job, = parse_wellfound(html, "https://wellfound.com/role/l/software-engineer/india", now=NOW)
    assert job.id == "wellfound:4760728"
    assert job.company == "Example"
    assert job.employment_type == "fulltime"
    assert job.location == "Pune, India"


def test_wellfound_structured_listing_with_invalid_url_is_skipped():
    html = '''<script type="application/ld+json">[
      {"@type":"JobPosting", "title":"Broken", "url":"javascript:alert(1)"},
      {"@type":"JobPosting", "title":"Junior Software Engineer",
       "url":"https://wellfound.com/jobs/4760728-junior-software-engineer"}
    ]</script>'''
    job, = parse_wellfound(html, "https://wellfound.com/role/l/software-engineer/india", now=NOW)
    assert job.id == "wellfound:4760728"
