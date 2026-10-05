"""Edit PROFILE when you are ready to use the watcher for your own search."""

from os import getenv
from profiles import Profile


PROFILE = Profile()
PROFILE_IS_EXAMPLE = True  # Set False after replacing the example preferences.

# A few broad searches are preferable to a large keyword cross-product.
LINKEDIN_SEARCHES = (
    "backend engineer intern",
    "software engineer intern",
    "junior software engineer",
    "graduate software engineer",
)
LINKEDIN_LOCATION = ""  # Fill in once your target region is known.
# India is a development search region, not a personal eligibility constraint.
INDEED_SEARCHES = (
    "software engineer intern",
    "junior software engineer",
    "python developer",
)
INDEED_COUNTRY = getenv("JOB_WATCHER_INDEED_COUNTRY", "India")
INDEED_LOCATION = getenv("JOB_WATCHER_INDEED_LOCATION", "")
NAUKRI_SEARCHES = (
    "software engineer fresher",
    "python developer",
    "backend developer",
)
NAUKRI_LOCATION = getenv("JOB_WATCHER_NAUKRI_LOCATION", "")
INTERNSHALA_URLS = (
    "https://internshala.com/internships/software-development-internship/",
    "https://internshala.com/internships/backend-development-internship/",
    "https://internshala.com/internships/python-internship/",
)
WELLFOUND_URLS = ("https://wellfound.com/role/l/software-engineer/india",)

ENABLED_SOURCES = tuple(
    name.strip() for name in (getenv("JOB_WATCHER_SOURCES") or "linkedin,internshala,indeed,naukri").split(",")
    if name.strip()
)
# Wellfound uses a fresh headless browser to read public listing data. Keep it
# optional while checking reliability across scheduled GitHub Actions runs.

ALERT_THRESHOLD = int(getenv("JOB_WATCHER_ALERT_THRESHOLD", "60"))
MAX_ALERTS_PER_RUN = int(getenv("JOB_WATCHER_MAX_ALERTS", "10"))
MAX_POSTING_AGE_DAYS = int(getenv("JOB_WATCHER_MAX_AGE_DAYS", "7"))
LINKEDIN_RESULTS_PER_SEARCH = 20
INDEED_RESULTS_PER_SEARCH = int(getenv("JOB_WATCHER_INDEED_RESULTS", "20"))
# At most 30 detail requests per run with the three default Naukri searches.
NAUKRI_RESULTS_PER_SEARCH = int(getenv("JOB_WATCHER_NAUKRI_RESULTS", "10"))
INTERNSHALA_MAX_CARDS_PER_URL = 50
WELLFOUND_MAX_CARDS_PER_URL = 50
# Hard caps keep enrichment and pagination small even with custom settings.
LINKEDIN_MAX_DETAIL_FETCHES = min(20, max(0, int(getenv("JOB_WATCHER_LINKEDIN_DETAILS", "20"))))
INTERNSHALA_MAX_DETAIL_FETCHES = min(10, max(0, int(getenv("JOB_WATCHER_INTERNSHALA_DETAILS", "10"))))
WELLFOUND_PAGES_PER_SEARCH = min(2, max(1, int(getenv("JOB_WATCHER_WELLFOUND_PAGES", "2"))))
HTTP_TIMEOUT = (5, 20)
