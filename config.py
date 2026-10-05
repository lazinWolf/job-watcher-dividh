"""Edit PROFILE when you are ready to use the watcher for your own search."""

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Profile:
    # These are example preferences for development, not the user's actual profile.
    role_terms: tuple[str, ...] = (
        "backend", "software engineer", "software engineering",
        "software developer", "software development", "sde",
        "platform engineer", "infrastructure engineer", "full stack",
    )
    skills: tuple[str, ...] = (
        "python", "go", "node.js", "fastapi", "postgresql", "docker", "linux",
    )
    job_types: tuple[str, ...] = ("internship", "fulltime")
    max_required_years: int = 2
    # Empty means no geographic exclusion. Add city/country names only when certain.
    allowed_locations: tuple[str, ...] = ()
    preferred_workplaces: tuple[str, ...] = ()  # remote, hybrid, onsite
    accept_unpaid_internships: bool = True


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
HTTP_TIMEOUT = (5, 20)
