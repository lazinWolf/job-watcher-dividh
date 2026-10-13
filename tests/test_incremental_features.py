from dataclasses import replace
import json
from pathlib import Path

import pytest

import main
from config import Profile
from evaluate import evaluate
from models import Job
from profiles import parse_profile
from sources.enrichment import enrich_jobs
from sources import internshala, linkedin, wellfound

PROFILE = Profile()
EXAMPLE_PROFILE = Path(__file__).parent.parent / "profile.example.json"


def job(number=1, **changes):
    return Job(**(dict(id=f"test:{number}", source="test", title="Backend Engineer Intern",
                      url=f"https://example.com/jobs/{number}") | changes))


def document(**profile):
    return json.dumps({"version": 1, "is_example": True, "profile": profile})


def test_profile_round_trip_defaults_and_company_exclusion():
    profile, example = parse_profile(document(excluded_companies=["  Example  "]))
    assert example and profile.excluded_companies == ("Example",)
    assert evaluate(job(company="example"), profile).reasons == ("excluded company",)
    assert evaluate(job(company="Example Labs"), profile).score is not None
    assert parse_profile(EXAMPLE_PROFILE.read_text())[1] is True


@pytest.mark.parametrize("changes", [
    {"skills": "Python"}, {"skills": [""]}, {"unknown": 1},
    {"max_required_years": True}, {"experience_years": -1},
    {"career_stage": "executive"}, {"preferred_workplaces": ["office"]},
    {"job_types": ["something"]}, {"role_terms": []}, {"accept_unpaid_internships": "false"},
])
def test_invalid_profile_is_rejected(changes):
    with pytest.raises(ValueError):
        parse_profile(document(**changes))


def test_example_profile_override_still_cannot_send_or_save(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)
    path = tmp_path / "profile.json"
    path.write_text(document())
    status, summary = main.run(tmp_path / "seen.json", profile_path=path,
        fetchers={"test": lambda: [job()]}, sender=lambda *_: pytest.fail("example must not send"))
    assert status == 0 and summary.selected == 1
    assert not (tmp_path / "seen.json").exists()


def test_environment_profile_changes_matching_and_is_validated_before_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_WATCHER_PROFILE_JSON", document(excluded_companies=["Example"]))
    _, summary = main.run(tmp_path / "seen.json", dry_run=True, fetchers={"test": lambda: [job(company="Example")]})
    assert summary.rejected == 1
    monkeypatch.setenv("JOB_WATCHER_PROFILE_JSON", "{broken")
    with pytest.raises(ValueError, match="valid JSON"):
        main.run(tmp_path / "seen.json", dry_run=True,
                 fetchers={"test": lambda: pytest.fail("must not fetch with invalid profile")})


def test_experienced_profile_can_match_senior_role():
    candidate = job(title="Senior Backend Engineer", experience_min_years=5)
    assert evaluate(candidate, PROFILE).score is None
    profile = Profile(career_stage="experienced", experience_years=6, max_required_years=6)
    assert evaluate(candidate, profile).score == 70
    assert evaluate(replace(candidate, experience_min_years=8), profile).score is None


@pytest.mark.parametrize("description", [
    "Minimum 3–5 years of experience required.",
    "Requirements\n- Experience: 3-5 years\nPreferred qualifications\n- 9 years of experience",
    "Must have 3 years of professional experience; 8 years of experience preferred.",
    "Must have 5 years of development experience and 1 year of Python experience.",
    "Minimum 3 years of experience required, 8 years of experience preferred.",
])
def test_required_ranges_and_strongest_requirement_are_checked(description):
    assert evaluate(job(description=description), PROFILE).score is None


def test_preferred_experience_and_colleague_experience_do_not_reject():
    description = "Requirements\nWork with senior engineers with 10 years of experience.\nPreferred qualifications\n5 years of experience."
    assert evaluate(job(description=description), PROFILE).score == 70


def test_description_requirement_is_not_hidden_by_sparse_source_field():
    result = evaluate(job(experience_min_years=0, description="Minimum 8 years of experience required."), PROFILE)
    assert result.reasons == ("requires 8+ years",)


def test_enrichment_is_capped_skips_processed_and_keeps_failures():
    candidates = [job(i) for i in range(6)] + [job(8, title="Office Assistant"), job(9, title="Senior Backend Engineer")]
    called = []
    def detail(candidate):
        called.append(candidate.id)
        if candidate.id == "test:2":
            raise RuntimeError("blocked")
        return replace(candidate, description="Build Python APIs")
    results = enrich_jobs(candidates, detail, limit=3, profile=PROFILE, processed_ids={"test:0"})
    assert called == ["test:1", "test:2", "test:3"]
    assert results[1].description and results[2] == candidates[2] and results[3].description
    assert len(results) == len(candidates)


def test_enrichment_stops_after_three_failures_and_ignores_existing_descriptions():
    called = []
    def fail(candidate):
        called.append(candidate.id)
        raise RuntimeError("blocked")
    candidates = [job(0, description="Already complete")] + [job(i) for i in range(1, 9)]
    assert enrich_jobs(candidates, fail, limit=20, profile=PROFILE) == candidates
    assert len(called) == 3


def test_public_detail_parsers_preserve_identity_and_ignore_training_and_perks():
    candidate = job(source="linkedin", employment_type=None)
    html = '<div class="show-more-less-html__markup"><p>Build Python APIs.</p><p>Requirements</p><p>Minimum 1 year of experience.</p></div><li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Employment type</h3><span class="description__job-criteria-text">Full-time</span></li>'
    enriched = linkedin.parse_detail(html, candidate)
    assert enriched.id == candidate.id and enriched.employment_type == "fulltime"
    assert "Build Python APIs" in enriched.description
    html = '''<div class="internship_details"><div class="text-container">Build Python APIs.</div>
    <h3 class="skills_heading">Skill(s) required</h3><div class="round_tabs_container"><span class="round_tabs">Python</span></div>
    <h3 class="perks_heading">Perks</h3><div class="round_tabs_container"><span class="round_tabs">Certificate</span></div>
    <div class="training_skills_container"><span class="round_tabs">Java</span></div></div>'''
    enriched = internshala.parse_detail(html, replace(candidate, source="internshala", skills=("Go",)))
    assert enriched.skills == ("Go", "Python")
    with pytest.raises(ValueError):
        linkedin.parse_detail("Please sign in", candidate)


def test_inline_html_does_not_hide_experience_and_block_headings_stay_separate():
    html = '''<div class="show-more-less-html__markup"><p>Requirements</p>
    <ul><li>Minimum <strong>5</strong> years of experience required.</li></ul>
    <p>Preferred qualifications</p><p><b>9</b> years of experience.</p></div>'''
    enriched = linkedin.parse_detail(html, job(source="linkedin"))
    assert "Minimum 5 years of experience required." in enriched.description
    assert evaluate(enriched, PROFILE).reasons == ("requires 5+ years",)
    html = html.replace("5", "1")
    enriched = linkedin.parse_detail(html, job(source="linkedin"))
    assert evaluate(enriched, PROFILE).score is not None  # preferred nine years does not reject


def test_wellfound_two_pages_preserve_queries_and_merge_overlap(monkeypatch):
    seen = []
    monkeypatch.setattr(wellfound, "WELLFOUND_URLS", ("https://wellfound.com/role/l/software-engineer/india?remote=true",))
    monkeypatch.setattr(wellfound, "WELLFOUND_PAGES_PER_SEARCH", 2)
    monkeypatch.setattr(wellfound, "get_browser_page", lambda url: seen.append(url) or url)
    first, second = job(1, source="wellfound"), job(2, source="wellfound")
    monkeypatch.setattr(wellfound, "parse_cards", lambda html, url: [first] if "page=1" in url else [replace(first, description="More detail"), second])
    jobs = wellfound.fetch_wellfound()
    assert len(jobs) == 2 and jobs[0].description == "More detail"
    assert len(seen) == 2 and all("remote=true" in url for url in seen)


def test_wellfound_later_page_failure_keeps_first_page(monkeypatch):
    monkeypatch.setattr(wellfound, "WELLFOUND_PAGES_PER_SEARCH", 2)
    def fetch(url):
        if "page=2" in url:
            raise RuntimeError("blocked")
        return "page"
    monkeypatch.setattr(wellfound, "get_browser_page", fetch)
    monkeypatch.setattr(wellfound, "parse_cards", lambda *_: [job()])
    assert len(wellfound.fetch_wellfound()) == 1


def test_report_and_deterministic_selection_do_not_change_state(tmp_path, capsys):
    state, report = tmp_path / "seen.json", tmp_path / "run-report.json"
    _, summary = main.run(state, dry_run=True, report_path=report,
                          fetchers={"test": lambda: [job(2), job(1, description="Python")]})
    payload = json.loads(report.read_text())
    assert payload["dry_run"] is True and payload["source_details"][0]["descriptions"] == 1
    assert summary.collected == 2 and not state.exists()
    assert "descriptions 1/2" in capsys.readouterr().out
    with pytest.raises(ValueError, match="separate"):
        main.run(state, dry_run=True, report_path=state, fetchers={})


def test_equal_scores_have_stable_selection_order(tmp_path, capsys):
    main.run(tmp_path / "seen.json", dry_run=True, fetchers={"test": lambda: [job(2), job(1)]})
    output = capsys.readouterr().out
    assert output.index("https://example.com/jobs/1") < output.index("https://example.com/jobs/2")


def test_runtime_profile_and_processed_ids_reach_enrichment(tmp_path, monkeypatch):
    from state import State, save_state
    path = tmp_path / "seen.json"
    save_state(path, State({"test:1"}))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(document(excluded_companies=["Example"]))
    monkeypatch.setenv("JOB_WATCHER_PROFILE_JSON", "{invalid")
    monkeypatch.setattr(main, "ENABLED_SOURCES", ("linkedin",))
    seen = {}
    def fetch(**settings):
        seen.update(settings)
        return [job()]
    monkeypatch.setitem(main.FETCHERS, "linkedin", fetch)
    _, summary = main.run(path, dry_run=True, profile_path=profile_path)
    assert seen["processed_ids"] == {"test:1"}
    assert seen["profile"].excluded_companies == ("Example",)
    assert summary.new == 0 and summary.collected == 1


def test_numeric_settings_name_the_bad_variable(monkeypatch):
    import config
    monkeypatch.setenv("JOB_WATCHER_MAX_ALERTS", "")
    assert config._env_int("JOB_WATCHER_MAX_ALERTS", 10) == 10
    monkeypatch.setenv("JOB_WATCHER_MAX_ALERTS", "ten")
    with pytest.raises(ValueError, match="JOB_WATCHER_MAX_ALERTS"):
        config._env_int("JOB_WATCHER_MAX_ALERTS", 10)
