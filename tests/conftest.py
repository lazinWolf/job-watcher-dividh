"""Keep the offline suite independent of personal settings and credentials."""

import pytest

import evaluate
import main
from profiles import Profile


@pytest.fixture(autouse=True)
def committed_defaults(monkeypatch):
    # Local profiles, Telegram secrets, and the Actions summary must not leak
    # into tests; tests that need them set their own values.
    for name in ("JOB_WATCHER_PROFILE_PATH", "JOB_WATCHER_PROFILE_JSON", "JOB_WATCHER_HISTORY_PATH",
                 "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    # Tests assert scores for the example profile, whatever config.py holds.
    monkeypatch.setattr(main, "PROFILE", Profile())
    monkeypatch.setattr(main, "PROFILE_IS_EXAMPLE", True)
    monkeypatch.setattr(main, "ALERT_THRESHOLD_OVERRIDE", None)
    monkeypatch.setattr(main, "MAX_ALERTS_PER_RUN", 10)
    monkeypatch.setattr(main, "HEALTH_ALERT_RUNS", 3)
    monkeypatch.setattr(main, "HISTORY_KEEP_RUNS", 500)
    monkeypatch.setattr(evaluate, "MAX_POSTING_AGE_DAYS", 7)
