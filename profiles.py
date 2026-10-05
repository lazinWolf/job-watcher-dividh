"""A small validated profile format; the example stays safe by default."""

from dataclasses import dataclass, fields
import json


@dataclass(frozen=True)
class Profile:
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
    allowed_locations: tuple[str, ...] = ()
    preferred_workplaces: tuple[str, ...] = ()
    accept_unpaid_internships: bool = True
    career_stage: str = "early"  # early, experienced, any
    experience_years: int = 0
    excluded_companies: tuple[str, ...] = ()


def parse_profile(content: str) -> tuple[Profile, bool]:
    try:
        document = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("Profile must contain valid JSON") from exc
    if not isinstance(document, dict) or set(document) != {"version", "is_example", "profile"}:
        raise ValueError("Profile document needs version, is_example, and profile")
    if type(document["version"]) is not int or document["version"] != 1:
        raise ValueError("Unsupported profile version")
    if type(document["is_example"]) is not bool:
        raise ValueError("Profile is_example must be true or false")
    values = document["profile"]
    if not isinstance(values, dict) or set(values) - {field.name for field in fields(Profile)}:
        raise ValueError("Profile has unknown fields or an invalid shape")
    values = dict(values)
    defaults = Profile()
    for field in fields(Profile):
        value = values.get(field.name, getattr(defaults, field.name))
        default = getattr(defaults, field.name)
        if isinstance(default, tuple):
            if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(f"Profile {field.name} must be a list of nonempty strings")
            value = tuple(dict.fromkeys(item.strip() for item in value))
        elif type(default) is bool:
            if type(value) is not bool:
                raise ValueError(f"Profile {field.name} must be true or false")
        elif type(default) is int:
            if type(value) is not int or not 0 <= value <= 80:
                raise ValueError(f"Profile {field.name} must be an integer from 0 to 80")
        elif not isinstance(value, str):
            raise ValueError(f"Profile {field.name} must be a string")
        values[field.name] = value
    if not values["role_terms"] or not values["job_types"]:
        raise ValueError("Profile must include target roles and job types")
    if set(values["job_types"]) - {"internship", "fulltime", "parttime", "contract", "temporary"}:
        raise ValueError("Profile has unsupported job types")
    if set(values["preferred_workplaces"]) - {"remote", "hybrid", "onsite"}:
        raise ValueError("Profile has unsupported workplace preferences")
    if values["career_stage"] not in {"early", "experienced", "any"}:
        raise ValueError("Profile career_stage must be early, experienced, or any")
    return Profile(**values), document["is_example"]
