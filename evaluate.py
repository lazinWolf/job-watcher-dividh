"""Deterministic eligibility and personal relevance scoring."""

from datetime import datetime, timezone
import re

from config import MAX_POSTING_AGE_DAYS, PROFILE, Profile
from models import Evaluation, Job

SENIOR_TITLE = re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|head of)\b", re.I)
# Words like "lead" or "manager" in an internship title do not make it senior.
INTERNSHIP_TITLE = re.compile(r"\b(?:intern|internship|trainee|apprentice(?:ship)?)\b", re.I)
ENTRY_TITLE = re.compile(r"\b(?:intern|internship|graduate|new grad|fresher|junior|entry.level|associate)\b", re.I)
EXPERIENCE_REQUIREMENT = re.compile(
    r"\b(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:\w+[ -]+){0,3}?(?:experience|exp)\b", re.I
)
MANDATORY_YEARS = re.compile(r"\b(\d{1,2})\s*\+\s*years?\s+(?:mandatory|required)\b", re.I)
EXPERIENCE_PREFIX = re.compile(r"\b(?:experience|exp)\s*:\s*(\d{1,2})(?:\s*[-–]\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b", re.I)
REQUIRED_HEADINGS = {"requirements", "qualifications", "minimum qualifications", "required qualifications"}
# Headings that end a requirements section. Requirement lists themselves are
# often short phrases, so only recognizable section names end it.
OTHER_HEADINGS = {
    "preferred qualifications", "nice to have", "benefits", "responsibilities", "about us",
    "key responsibilities", "what you'll do", "what you will do", "the role", "role overview",
    "job description", "company description", "who we are", "our team", "perks",
    "what we offer", "compensation", "how to apply",
}
TECH_ALIASES = {
    "node.js": (r"\bnode(?:\.js|js)\b",),
    "go": (r"\bgo\b", r"\bgolang\b"),
    "postgresql": (r"\bpostgres(?:ql)?\b",),
    "fastapi": (r"\bfastapi\b",),
    "python": (r"\bpython\b",),
    "docker": (r"\bdocker\b",),
    "linux": (r"\blinux\b",),
}


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))


def _technology_matches(job: Job, profile: Profile) -> list[str]:
    # The word "go" in prose is ambiguous. Only a title or explicit skill tag
    # can count it; "Golang" can count anywhere.
    explicit = " ".join((job.title, *job.skills))
    full = " ".join((explicit, job.description or ""))
    found = []
    for skill in profile.skills:
        key = skill.casefold()
        aliases = TECH_ALIASES.get(key, (r"(?<!\w)" + re.escape(skill) + r"(?!\w)",))
        haystack = explicit if key == "go" else full
        if any(re.search(pattern, haystack, re.I) for pattern in aliases):
            found.append(skill)
        elif key == "go" and re.search(r"\bgolang\b", full, re.I):
            found.append(skill)
    return found


def _about_heading(heading: str) -> bool:
    # "About the company", "Why join us": short, no numbers.
    return (heading.startswith(("about ", "why ")) and len(heading.split()) <= 4
            and not re.search(r"\d", heading))


def _mandatory_years(description: str | None) -> int | None:
    if not description:
        return None
    years = []
    required_section = False
    for line in re.split(r"[\n;.!?,]+", description):
        heading = line.strip(" *#:-").casefold()
        if heading in REQUIRED_HEADINGS:
            required_section = True
            continue
        if heading in OTHER_HEADINGS or _about_heading(heading):
            required_section = False
            continue
        if re.search(r"\b(?:preferred|nice to have|a plus|bonus)\b", line, re.I):
            continue
        if re.search(r"\b(?:work|collaborate|partner|learn)\s+(?:closely\s+)?with\b", line, re.I):
            continue
        if required_section or re.search(r"\b(?:required|mandatory|must have|minimum|at least)\b", line, re.I):
            years.extend(int(m.group(1)) for m in EXPERIENCE_REQUIREMENT.finditer(line))
            years.extend(int(m.group(1)) for m in MANDATORY_YEARS.finditer(line))
            years.extend(int(m.group(1)) for m in EXPERIENCE_PREFIX.finditer(line))
    return max(years) if years else None


def role_relevant(job: Job, profile: Profile = PROFILE) -> bool:
    """Broad enough to enrich jobs that lack skill details or career evidence."""
    return any(_contains(job.title, term) for term in profile.role_terms) or bool(
        re.search(r"\b(?:software|developer|engineering)\b", job.title, re.I)
    )


def evaluate(job: Job, profile: Profile = PROFILE, *, now: datetime | None = None) -> Evaluation:
    now = now or datetime.now(timezone.utc)
    title = job.title.strip()
    if job.company and job.company.casefold().strip() in {name.casefold().strip() for name in profile.excluded_companies}:
        return Evaluation(None, ("excluded company",))
    if profile.career_stage == "early" and SENIOR_TITLE.search(title) and not INTERNSHIP_TITLE.search(title):
        return Evaluation(None, ("senior role title",))

    years = job.experience_min_years
    described_years = _mandatory_years(title + "\n" + (job.description or ""))
    if described_years is not None:
        years = max(years, described_years) if years is not None else described_years
    if years is not None and years > profile.max_required_years:
        return Evaluation(None, (f"requires {years}+ years",))

    if job.employment_type and job.employment_type not in profile.job_types:
        return Evaluation(None, (f"{job.employment_type} is outside selected job types",))
    if (job.employment_type == "internship" and not profile.accept_unpaid_internships
            and job.compensation and re.search(r"\b(?:unpaid|no stipend)\b", job.compensation, re.I)):
        return Evaluation(None, ("unpaid internship",))

    if profile.allowed_locations and job.location:
        location = job.location.casefold()
        # "Remote" alone does not say where a person is eligible to work.
        if not any(place.casefold() in location for place in profile.allowed_locations):
            # A city-only preference cannot establish eligibility for a remote
            # role labelled with a country, so keep it for manual review.
            if "remote" not in location and "everywhere" not in location:
                return Evaluation(None, ("location outside selected places",))

    if job.posted_at and (now - job.posted_at).total_seconds() > MAX_POSTING_AGE_DAYS * 86400:
        return Evaluation(None, ("older than posting-age limit",))

    score = 0
    reasons = []
    if any(_contains(title, term) for term in profile.role_terms):
        score += 45
        reasons.append("preferred role")
    elif re.search(r"\b(?:software|developer|engineering)\b", title, re.I):
        score += 15
        reasons.append("related engineering role")

    early = job.employment_type == "internship" or ENTRY_TITLE.search(title)
    if early and profile.career_stage in {"early", "any"}:
        score += 25
        reasons.append("early-career role")
    elif profile.career_stage == "early" and years is not None and years <= max(1, profile.experience_years):
        score += 25
        reasons.append("0–1 years experience" if years <= 1 else "experience fits profile")
    elif profile.career_stage == "early" and years is not None:
        score += 15
        reasons.append(f"{years} years experience")
    elif not early and years is not None:
        score += 25 if years <= profile.experience_years else 15
        reasons.append("experience fits profile" if years <= profile.experience_years else "experience stretch")
    elif SENIOR_TITLE.search(title) and profile.career_stage in {"experienced", "any"}:
        score += 25
        reasons.append("experienced role")

    skills = _technology_matches(job, profile)
    if skills:
        score += min(20, len(skills) * 5)
        reasons.append("skills: " + ", ".join(skills[:4]))

    if job.workplace_type and job.workplace_type in profile.preferred_workplaces:
        score += 5
        reasons.append(f"preferred {job.workplace_type} work")

    if job.posted_at and 0 <= (now - job.posted_at).total_seconds() <= 3 * 86400:
        score += 5
        reasons.append("posted recently")
    return Evaluation(score, tuple(reasons))
