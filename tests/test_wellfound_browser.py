"""Wellfound's public Next.js data and isolated browser fetch."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

from sources import wellfound

FIXTURE = Path(__file__).parent / "fixtures" / "wellfound_apollo.json"
PAGE_URL = "https://wellfound.com/role/l/software-engineer/india"


def test_apollo_data_supplies_fields_needed_for_scoring():
    payload = FIXTURE.read_text()
    html = f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'
    jobs = wellfound.parse_cards(html, PAGE_URL)
    assert len(jobs) == 2
    product, deployment = jobs
    assert product.id == "wellfound:4718964"
    assert product.title == "Software Engineer (Product)"
    assert product.company == "Avoca AI"
    assert product.url == "https://wellfound.com/jobs/4718964-software-engineer-product"
    assert product.location == "Bengaluru"
    assert product.description == "Build Python services with the product team."
    assert product.posted_at == datetime.fromtimestamp(1789516781, timezone.utc)
    assert product.employment_type == "fulltime"
    assert product.workplace_type == "onsite"
    assert deployment.location == "Remote • India"
    assert deployment.workplace_type == "remote"


def test_fresh_browser_fetch_uses_isolated_profile(monkeypatch):
    html = '<script id="__NEXT_DATA__">{}</script>'
    monkeypatch.setattr(wellfound.shutil, "which", lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None)

    def fake_run(args, **kwargs):
        profile = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--user-data-dir="))
        assert Path(profile).is_dir()
        assert "--headless=new" in args
        assert "--no-sandbox" not in args
        assert args[-1] == PAGE_URL
        assert kwargs["timeout"] == wellfound.BROWSER_TIMEOUT_SECONDS
        return SimpleNamespace(returncode=0, stdout=html)

    monkeypatch.setattr(wellfound.subprocess, "run", fake_run)
    assert wellfound.get_browser_page(PAGE_URL) == html


def test_browser_absence_is_reported(monkeypatch):
    monkeypatch.setattr(wellfound.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Chrome or Chromium"):
        wellfound.get_browser_page(PAGE_URL)


def test_profile_cleanup_failure_keeps_the_fetched_page(monkeypatch):
    html = '<script id="__NEXT_DATA__">{}</script>'
    monkeypatch.setattr(wellfound.shutil, "which", lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None)
    monkeypatch.setattr(wellfound.subprocess, "run", lambda args, **_: SimpleNamespace(returncode=0, stdout=html))

    class RacingProfile(tempfile.TemporaryDirectory):
        # Chrome helpers can add files while the folder is being removed.
        def cleanup(self):
            super().cleanup()
            if not self._ignore_cleanup_errors:
                raise OSError(39, "Directory not empty", self.name + "/Default")

    monkeypatch.setattr(wellfound.tempfile, "TemporaryDirectory", RacingProfile)
    assert wellfound.get_browser_page(PAGE_URL) == html
