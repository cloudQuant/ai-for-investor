from datetime import datetime, timezone
from math import log10
from typing import Any

from app.models.discovery import OpenSourceProject


SCORE_DISCLAIMER = "Automatic score is an editorial aid only, not a recommendation or investment advice."


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def score_stars(project: OpenSourceProject) -> float:
    return clamp(log10(max(project.stars or 0, 0) + 1) / 4 * 100)


def score_activity(project: OpenSourceProject) -> float:
    if not project.latest_commit_at:
        return 20.0
    latest_commit = project.latest_commit_at
    if latest_commit.tzinfo is None:
        latest_commit = latest_commit.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - latest_commit).days
    if age_days <= 30:
        return 100.0
    if age_days <= 180:
        return 75.0
    if age_days <= 365:
        return 50.0
    return 25.0


def score_documentation(project: OpenSourceProject) -> float:
    text = " ".join(filter(None, [project.description, project.readme_summary])).lower()
    score = 20.0
    if "doc" in text or "documentation" in text:
        score += 25.0
    if "example" in text or "reproduc" in text:
        score += 25.0
    if "test" in text or "notebook" in text:
        score += 15.0
    if len(text) > 120:
        score += 15.0
    return clamp(score)


def score_license(project: OpenSourceProject) -> float:
    if not project.license:
        return 20.0
    if project.license.lower() in {"mit", "apache-2.0", "bsd-3-clause", "bsd-2-clause"}:
        return 100.0
    return 70.0


def score_relevance(project: OpenSourceProject) -> float:
    text = " ".join(
        filter(
            None,
            [project.repo_full_name, project.description, project.readme_summary, " ".join(project.topics or [])],
        )
    ).lower()
    keywords = ["ai", "invest", "trading", "quant", "backtest", "portfolio", "agent", "research"]
    matches = sum(1 for keyword in keywords if keyword in text)
    return clamp(matches / 5 * 100)


def calculate_project_score(project: OpenSourceProject) -> dict[str, Any]:
    criteria = {
        "stars": score_stars(project),
        "activity": score_activity(project),
        "documentation": score_documentation(project),
        "license": score_license(project),
        "relevance": score_relevance(project),
    }
    overall = round(sum(criteria.values()) / len(criteria), 2)
    return {
        "criteria": criteria,
        "overall_score": overall,
        "editorial_aid_only": True,
        "disclaimer": SCORE_DISCLAIMER,
    }
