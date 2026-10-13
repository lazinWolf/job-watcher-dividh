"""Optional collector for publicly accessible Wellfound search pages."""

from datetime import datetime, timezone
import json
import logging
import re
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from config import WELLFOUND_MAX_CARDS_PER_URL, WELLFOUND_PAGES_PER_SEARCH, WELLFOUND_URLS
from models import Job, canonical_url, job_id, merge_jobs, parse_posted_at

LOGGER = logging.getLogger(__name__)
JOB_HREF = re.compile(r"^/jobs/(\d+)-")
BROWSER_TIMEOUT_SECONDS = 60


def get_browser_page(url: str) -> str:
    """Fetch one public page in an isolated, disposable headless Chrome profile."""
    browser = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not browser:
        raise RuntimeError("Wellfound requires Google Chrome or Chromium on PATH")
    with tempfile.TemporaryDirectory(prefix="job-watcher-wellfound-") as profile:
        try:
            result = subprocess.run(
                [browser, "--headless=new", "--disable-gpu",
                 "--disable-dev-shm-usage", "--no-first-run",
                 f"--user-data-dir={profile}", "--dump-dom", url],
                capture_output=True, text=True, timeout=BROWSER_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Wellfound browser fetch timed out") from exc
    if result.returncode != 0:
        raise RuntimeError(f"Wellfound browser exited with status {result.returncode}")
    if not result.stdout.strip():
        raise ValueError("Wellfound browser returned an empty page")
    return result.stdout


def _apollo_jobs(soup: BeautifulSoup) -> list[Job]:
    script = soup.select_one("script#__NEXT_DATA__")
    if script is None:
        return []
    try:
        graph = json.loads(script.string or script.get_text())["props"]["pageProps"]["apolloState"]["data"]
    except (TypeError, ValueError, KeyError):
        return []
    if not isinstance(graph, dict):
        return []
    jobs = []
    seen = set()
    for key, company in graph.items():
        if not key.startswith("StartupResult:") or not isinstance(company, dict):
            continue
        for reference in company.get("highlightedJobListings") or []:
            if not isinstance(reference, dict):
                continue
            listing = graph.get(reference.get("__ref"))
            if not isinstance(listing, dict):
                continue
            source_id = str(listing.get("id") or "").strip()
            title = listing.get("title")
            slug = listing.get("slug")
            if not source_id.isdigit() or not isinstance(title, str) or not title.strip() or not isinstance(slug, str) or not slug:
                continue
            if source_id in seen:
                continue
            seen.add(source_id)
            url = canonical_url(f"https://wellfound.com/jobs/{source_id}-{slug}")
            remote_config = listing.get("remoteConfig") or {}
            remote_kind = remote_config.get("kind") if isinstance(remote_config, dict) else None
            workplace = {"REMOTE": "remote", "ONSITE": "onsite", "ONSITE_OR_REMOTE": "hybrid"}.get(remote_kind)
            locations = listing.get("locationNames") or []
            if not isinstance(locations, list):
                locations = []
            location = ", ".join(place for place in locations if isinstance(place, str)) or None
            if workplace == "remote":
                remote_places = listing.get("acceptedRemoteLocationNames") or []
                if isinstance(remote_places, list) and remote_places:
                    location = ", ".join(place for place in remote_places if isinstance(place, str)) or location
                location = f"Remote • {location}" if location else "Remote"
            elif workplace == "hybrid" and location:
                location = f"Onsite or remote • {location}"
            posted = listing.get("liveStartAt")
            try:
                posted_at = datetime.fromtimestamp(posted, timezone.utc) if isinstance(posted, (int, float)) else None
            except (OverflowError, OSError, ValueError):
                posted_at = None
            years = listing.get("yearsExperienceMin")
            jobs.append(Job(
                id=job_id("wellfound", url, source_id), source="wellfound",
                title=title.strip(), url=url,
                company=(company.get("name") or "").strip() or None,
                location=location,
                description=listing.get("description") or None,
                compensation=listing.get("compensation") or None,
                posted_at=posted_at,
                employment_type=_employment(listing.get("jobType")),
                workplace_type=workplace,
                experience_min_years=years if isinstance(years, int) and not isinstance(years, bool) else None,
            ))
    return jobs


def _structured_jobs(soup: BeautifulSoup, page_url: str) -> list[Job]:
    jobs = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            document = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        queue = document if isinstance(document, list) else [document]
        while queue:
            item = queue.pop()
            if not isinstance(item, dict):
                continue
            queue.extend(item.get("@graph", []))
            if item.get("@type") != "JobPosting":
                continue
            title = item.get("title")
            raw_url = item.get("url")
            if not isinstance(title, str) or not isinstance(raw_url, str):
                continue
            try:
                url = canonical_url(urljoin(page_url, raw_url))
            except ValueError:
                continue
            organization = item.get("hiringOrganization") or {}
            place = item.get("jobLocation") or {}
            if isinstance(place, list):
                place = place[0] if place else {}
            address = place.get("address", {}) if isinstance(place, dict) else {}
            location = ", ".join(filter(None, (address.get("addressLocality"), address.get("addressCountry")))) if isinstance(address, dict) else None
            jobs.append(Job(
                id=job_id("wellfound", url, _id_from_url(url)), source="wellfound",
                title=title.strip(), url=url,
                company=organization.get("name") if isinstance(organization, dict) else None,
                location=location or None, posted_at=parse_posted_at(item.get("datePosted")),
                employment_type=_employment(item.get("employmentType")),
            ))
    return jobs


def _id_from_url(url: str) -> str | None:
    match = re.search(r"/jobs/(\d+)-", url)
    return match.group(1) if match else None


def _employment(value: object) -> str | None:
    text = str(value or "").casefold()
    return "internship" if "intern" in text else "fulltime" if "full" in text else None


def parse_cards(html: str, page_url: str, *, now: datetime | None = None) -> list[Job]:
    now = now or datetime.now(timezone.utc)
    soup = BeautifulSoup(html, "html.parser")
    jobs = _apollo_jobs(soup)
    if not jobs:
        LOGGER.warning("Wellfound embedded job data unavailable; using fallback parser")
        jobs = _structured_jobs(soup, page_url)
    if jobs:
        if len(jobs) > WELLFOUND_MAX_CARDS_PER_URL:
            LOGGER.info("Wellfound: %d embedded listings; truncated to card limit %d", len(jobs), WELLFOUND_MAX_CARDS_PER_URL)
        return jobs[:WELLFOUND_MAX_CARDS_PER_URL]
    # The public search page has, when accessible, job links grouped with a
    # company and short listing text. Keep this fallback conservative.
    for anchor in soup.select('a[href^="/jobs/"]'):
        href = anchor.get("href", "")
        match = JOB_HREF.match(href)
        title = anchor.get_text(" ", strip=True)
        if not match or not title or len(title) > 120:
            continue
        card = anchor
        for parent in anchor.parents:
            if parent.name not in {"div", "article", "li"}:
                continue
            card = parent
            if parent.select_one('a[href^="/company/"]'):
                break
            if len(parent.get_text(" ", strip=True)) > 600:
                card = anchor.parent
                break
        company_link = card.select_one('a[href^="/company/"]') if card else None
        card_text = card.get_text(" ", strip=True) if card else title
        experience = re.search(r"\b(\d+)\s+years?\s+of\s+exp\b", card_text, re.I)
        posted = re.search(r"\b(?:today|yesterday|\d+\s+(?:hours?|days?|weeks?|months?)\s+ago)\b", card_text, re.I)
        location = None
        workplace = None
        place = re.search(r"\b(Remote only|Onsite or remote|In office)\s*[•|]??\s*([^•\n]{2,70})", card_text, re.I)
        if place:
            location = place.group(0).strip()
            workplace = "remote" if "remote only" in location.casefold() else "hybrid" if "onsite or remote" in location.casefold() else "onsite"
        url = canonical_url(urljoin(page_url, href))
        jobs.append(Job(
            id=job_id("wellfound", url, match.group(1)), source="wellfound", title=title,
            url=url, company=company_link.get_text(" ", strip=True) if company_link else None,
            location=location, posted_at=parse_posted_at(posted.group(0), now) if posted else None,
            experience_min_years=int(experience.group(1)) if experience else None,
            employment_type=_employment(card_text[:200]), workplace_type=workplace,
        ))
        if len(jobs) >= WELLFOUND_MAX_CARDS_PER_URL:
            break
    if not jobs:
        raise ValueError("Wellfound page had no recognizable public listing cards")
    return jobs


def fetch_wellfound() -> list[Job]:
    jobs: dict[str, Job] = {}
    failures = []
    for base_url in WELLFOUND_URLS:
        parts = urlsplit(base_url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        start_page = int(query.get("page", "1"))
        seen_in_search: set[str] = set()
        for page in range(start_page, start_page + WELLFOUND_PAGES_PER_SEARCH):
            page_query = query | {"page": str(page)}
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(page_query), ""))
            try:
                found = parse_cards(get_browser_page(url), url)
                new_ids = {job.id for job in found} - seen_in_search
                LOGGER.info("Wellfound page %d: %d listings, %d new IDs, descriptions %d/%d; page limit %d",
                            page, len(found), len(new_ids), sum(bool(job.description) for job in found),
                            len(found), WELLFOUND_PAGES_PER_SEARCH)
                for job in found:
                    jobs[job.id] = merge_jobs(jobs[job.id], job) if job.id in jobs else job
                seen_in_search.update(new_ids)
                if not new_ids:
                    break
            except Exception as exc:
                failures.append(f"{url}: {type(exc).__name__}: {exc}")
                break
    if not jobs and failures:
        raise RuntimeError("; ".join(failures))
    for failure in failures:
        LOGGER.warning("Wellfound query failed: %s", failure)
    return list(jobs.values())
