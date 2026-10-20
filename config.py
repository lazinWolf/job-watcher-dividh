"""Edit PROFILE when you are ready to use the watcher for your own search."""

from os import getenv
from profiles import Profile


def _env_override(name: str) -> int | None:
    return _env_int(name, 0) if getenv(name) else None


def _env_int(name: str, default: int) -> int:
    value = getenv(name) or str(default)
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, not {value!r}") from None


PROFILE = Profile()
PROFILE_IS_EXAMPLE = True  # Set False after replacing the example preferences.

# Searches, regions, and the alert threshold are profile settings (profiles.py).
# These environment variables still override the profile when set.
INDEED_COUNTRY_OVERRIDE = getenv("JOB_WATCHER_INDEED_COUNTRY", "")
INDEED_LOCATION_OVERRIDE = getenv("JOB_WATCHER_INDEED_LOCATION", "")
NAUKRI_LOCATION_OVERRIDE = getenv("JOB_WATCHER_NAUKRI_LOCATION", "")
ALERT_THRESHOLD_OVERRIDE = _env_override("JOB_WATCHER_ALERT_THRESHOLD")

ENABLED_SOURCES = tuple(
    name.strip() for name in (getenv("JOB_WATCHER_SOURCES") or "linkedin,internshala,indeed,naukri,wellfound").split(",")
    if name.strip()
)
# Wellfound uses a fresh headless browser, so it needs Chrome or Chromium on PATH.

MAX_ALERTS_PER_RUN = _env_int("JOB_WATCHER_MAX_ALERTS", 40)  # jobs per digest run
MAX_POSTING_AGE_DAYS = _env_int("JOB_WATCHER_MAX_AGE_DAYS", 7)
LINKEDIN_RESULTS_PER_SEARCH = 20
INDEED_RESULTS_PER_SEARCH = _env_int("JOB_WATCHER_INDEED_RESULTS", 20)
# At most 30 detail requests per run with the three default Naukri searches.
NAUKRI_RESULTS_PER_SEARCH = _env_int("JOB_WATCHER_NAUKRI_RESULTS", 10)
INTERNSHALA_MAX_CARDS_PER_URL = 50
WELLFOUND_MAX_CARDS_PER_URL = 50
# Hard caps keep enrichment and pagination small even with custom settings.
LINKEDIN_MAX_DETAIL_FETCHES = min(20, max(0, _env_int("JOB_WATCHER_LINKEDIN_DETAILS", 20)))
INTERNSHALA_MAX_DETAIL_FETCHES = min(10, max(0, _env_int("JOB_WATCHER_INTERNSHALA_DETAILS", 10)))
WELLFOUND_PAGES_PER_SEARCH = min(2, max(1, _env_int("JOB_WATCHER_WELLFOUND_PAGES", 2)))
HTTP_TIMEOUT = (5, 20)

# Monitoring: alert after this many consecutive failed or empty runs of a
# source, and keep this many run records in the history file.
HEALTH_ALERT_RUNS = max(1, _env_int("JOB_WATCHER_HEALTH_RUNS", 3))
HISTORY_KEEP_RUNS = max(1, _env_int("JOB_WATCHER_HISTORY_RUNS", 500))
