import json

import pytest

import main
from models import Job
from state import State, save_state
from telemetry import append_history, health_changes, read_history


def job(number: int, title: str = "Backend Engineer Intern", **changes) -> Job:
    return Job(**(dict(id=f"test:{number}", source="test", title=title,
                       url=f"https://example.com/jobs/{number}", company="Example",
                       description="Private description text") | changes))


def run_record(**sources) -> dict:
    """sources: name -> listing count, or an error string for a failed run."""
    return {"sources": [
        {"source": name, "status": "failed", "error": value} if isinstance(value, str)
        else {"source": name, "status": "ok", "listings": value}
        for name, value in sources.items()
    ]}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", False)


def test_report_records_every_decision_outcome_without_descriptions(tmp_path, monkeypatch, live):
    monkeypatch.setattr(main, "MAX_ALERTS_PER_RUN", 3)
    monkeypatch.setattr("telegram.MESSAGE_LIMIT", 300)  # one company per digest message
    original = main.evaluate
    def evaluate(candidate, profile):
        if candidate.id == "test:7":
            raise RuntimeError("bad listing")
        return original(candidate, profile)
    monkeypatch.setattr(main, "evaluate", evaluate)
    jobs = [job(1, company="A"), job(2, company="B"), job(3, company="C"), job(4), job(5, "Senior Backend Engineer"),
            job(6, "Office Assistant"), job(7)]
    def sender(text):
        if "jobs/2" in text:
            raise RuntimeError("delivery unavailable")
    report = tmp_path / "report.json"
    status, summary = main.run(tmp_path / "seen.json", init_state=True, report_path=report,
                               fetchers={"test": lambda: jobs}, sender=sender)
    payload = json.loads(report.read_text())
    outcomes = {decision["id"]: decision["outcome"] for decision in payload["decisions"]}
    assert status == 1
    assert outcomes == {"test:1": "sent", "test:2": "delivery_failed", "test:3": "deferred",
                        "test:4": "deferred", "test:5": "rejected", "test:6": "below_threshold",
                        "test:7": "evaluation_failed"}
    assert payload["version"] == 2 and payload["run_id"] and payload["finished_at"]
    assert payload["rejection_reasons"] == {"senior role title": 1}
    assert "Private description text" not in report.read_text()
    assert summary.deferred == 3  # the failed delivery also stays unprocessed for retry


def test_dry_run_reports_would_send_but_writes_no_history_or_health(tmp_path):
    report = tmp_path / "report.json"
    main.run(tmp_path / "seen.json", dry_run=True, report_path=report,
             fetchers={"test": lambda: [job(1)]}, notifier=lambda _: pytest.fail("dry run must not notify"))
    assert json.loads(report.read_text())["decisions"][0]["outcome"] == "would_send"
    assert not (tmp_path / "history.jsonl").exists()


def test_all_sources_failing_still_records_history_and_report(tmp_path, live):
    def fail():
        raise RuntimeError("blocked by runner")
    report, history = tmp_path / "report.json", tmp_path / "history.jsonl"
    status, _ = main.run(tmp_path / "seen.json", init_state=True, report_path=report,
                         fetchers={"linkedin": fail})
    assert status == 1 and json.loads(report.read_text())["sources_failed"] == 1
    record, = read_history(history)
    assert record["sources"] == [{"source": "linkedin", "status": "failed",
                                  "seconds": record["sources"][0]["seconds"],
                                  "error": "RuntimeError: blocked by runner"}]


def test_history_is_trimmed_and_survives_a_corrupt_line(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text('{"run_id": "a"}\nnot json\n{"run_id": "b"}\n')
    history = append_history(path, {"run_id": "c"}, keep=2)
    assert [record["run_id"] for record in history] == ["b", "c"]
    assert [record["run_id"] for record in read_history(path)] == ["b", "c"]
    assert [item.name for item in tmp_path.iterdir()] == ["history.jsonl"]


def test_health_alerts_once_at_threshold_and_on_recovery():
    history = [run_record(linkedin=5)]
    for _ in range(2):
        history.append(run_record(linkedin="RuntimeError: blocked"))
        assert health_changes(history, threshold=3) == []
    history.append(run_record(linkedin=0))
    alert, = health_changes(history, threshold=3)
    assert "linkedin" in alert and "3 runs" in alert and "returned no listings" in alert
    history.append(run_record(linkedin="RuntimeError: blocked"))
    assert health_changes(history, threshold=3) == []
    history.append(run_record(linkedin=12))
    recovery, = health_changes(history, threshold=3)
    assert "working again" in recovery and "12 listings" in recovery and "4 unhealthy" in recovery
    history.append(run_record(linkedin=9))
    assert health_changes(history, threshold=3) == []


def test_runs_without_a_source_do_not_affect_its_streak():
    history = [run_record(naukri="RuntimeError: 406"), run_record(indeed=4),
               run_record(naukri="RuntimeError: 406"), run_record(indeed=3),
               run_record(naukri="RuntimeError: 406", indeed=2)]
    alert, = health_changes(history, threshold=3)
    assert "naukri" in alert and "RuntimeError: 406" in alert


def test_health_messages_are_sent_and_failures_do_not_change_status(tmp_path, live):
    seen, history = tmp_path / "seen.json", tmp_path / "history.jsonl"
    save_state(seen, State())
    history.write_text("".join(json.dumps(run_record(test=0)) + "\n" for _ in range(2)))
    sent = []
    def notifier(message):
        sent.append(message)
        raise RuntimeError("telegram down")
    status, summary = main.run(seen, fetchers={"test": lambda: []}, sender=lambda *_: None, notifier=notifier)
    assert status == 0 and len(sent) == 1 and summary.health == sent
    assert len(read_history(history)) == 3
