from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypedDict

RoleFamily = Literal["IC", "EM", "PM", "TPM", "Other"]
PersonType = Literal["internal", "candidate"]

_TITLE_KEYWORDS = (
    "engineer",
    "developer",
    "manager",
    "architect",
    "scientist",
    "program manager",
    "product manager",
    "technical program manager",
    "consultant",
    "lead",
    "director",
    "vp",
    "head of",
)

_NAME_STOPWORDS = {
    "resume",
    "curriculum",
    "vitae",
    "email",
    "phone",
    "linkedin",
    "github",
    "summary",
    "experience",
    "education",
    "skills",
    "projects",
    "certifications",
    "publications",
}


class DerivedPersonAttributes(TypedDict):
    person_id: str
    type: PersonType | None
    role_family: RoleFamily
    level: str | None
    current_title: str | None
    confidence: dict[str, Literal["high", "medium", "low"]]


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_").lower()
    return slug or "unknown_person"


def _clean_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[Page ") and line.endswith("]"):
            continue
        line = re.sub(r"\s+", " ", line)
        lines.append(line)
    return lines


def _is_name_like(line: str) -> bool:
    if "@" in line or re.search(r"\d", line):
        return False
    lowered = line.lower()
    if any(token in lowered for token in _NAME_STOPWORDS):
        return False
    words = line.split()
    if not (2 <= len(words) <= 4):
        return False
    for word in words:
        token = word.strip(".,")
        if not re.fullmatch(r"[A-Za-z][A-Za-z'`.-]*", token):
            return False
        if token.isupper():
            continue
        if not token[0].isupper():
            return False
    return True


def _extract_name(lines: list[str]) -> tuple[str | None, Literal["high", "low"]]:
    for line in lines[:30]:
        if _is_name_like(line):
            return line, "high"
    return None, "low"


def _extract_current_title(lines: list[str]) -> tuple[str | None, Literal["medium", "low"]]:
    for line in lines[:60]:
        lowered = line.lower()
        if any(keyword in lowered for keyword in _TITLE_KEYWORDS):
            words = line.split()
            if 2 <= len(words) <= 12:
                return _normalize_title(line), "medium"
    return None, "low"


def _normalize_title(raw_title: str) -> str:
    title = re.sub(r"\s*@\s*.+$", "", raw_title).strip()

    # Remove " at Company" suffixes while preserving role text.
    title = re.sub(
        r"\s+at\s+[A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*){0,3}\s*$",
        "",
        title,
    ).strip()

    # Remove trailing company tokens after separators like "|" or "-".
    separator_match = re.match(r"^(.*?)(?:\s*[|-]\s*)([^|@-]+)$", title)
    if separator_match:
        left, right = separator_match.group(1).strip(), separator_match.group(2).strip()
        right_lower = right.lower()
        company_terms = (
            "inc",
            "llc",
            "ltd",
            "corp",
            "corporation",
            "company",
            "technologies",
            "technology",
            "labs",
            "systems",
            "solutions",
        )
        if any(term in right_lower for term in company_terms):
            title = left

    return title.strip()


def _infer_level(current_title: str | None) -> tuple[str | None, Literal["medium", "low"]]:
    if not current_title:
        return None, "low"
    lowered = current_title.lower()
    if "principal" in lowered:
        return "Principal", "medium"
    if "staff" in lowered:
        return "Staff", "medium"
    if "senior" in lowered or "sr " in f"{lowered} ":
        return "Senior", "medium"
    if "lead" in lowered:
        return "Lead", "medium"
    if "junior" in lowered or "jr " in f"{lowered} ":
        return "Junior", "medium"
    if "intern" in lowered:
        return "Intern", "medium"
    return None, "low"


def _infer_role_family(current_title: str | None) -> tuple[RoleFamily, Literal["high", "medium", "low"]]:
    if not current_title:
        return "Other", "low"

    lowered = current_title.lower()
    if "technical program manager" in lowered or re.search(r"\btpm\b", lowered):
        return "TPM", "high"
    if "product manager" in lowered or re.search(r"\bproduct\b", lowered):
        return "PM", "high"
    if (
        "engineering manager" in lowered
        or "head of engineering" in lowered
        or "director of engineering" in lowered
        or "manager" in lowered
    ):
        return "EM", "medium"
    if any(
        token in lowered
        for token in (
            "engineer",
            "developer",
            "architect",
            "scientist",
            "sre",
            "devops",
            "qa",
        )
    ):
        return "IC", "high"
    return "Other", "low"


def derive_person_attributes(extracted_text: str, source_pdf: str | Path) -> DerivedPersonAttributes:
    lines = _clean_lines(extracted_text)
    name, name_confidence = _extract_name(lines)
    current_title, title_confidence = _extract_current_title(lines)
    role_family, role_confidence = _infer_role_family(current_title)
    level, level_confidence = _infer_level(current_title)

    source_stem = Path(source_pdf).expanduser().resolve().stem
    person_id_source = source_stem or name
    person_id = _safe_slug(person_id_source) if person_id_source else "unknown_person"

    return {
        "person_id": person_id or "unknown_person",
        "type": None,
        "role_family": role_family,
        "level": level,
        "current_title": current_title,
        "confidence": {
            "person_id": "high" if source_stem else name_confidence,
            "type": "low",
            "role_family": role_confidence,
            "level": level_confidence,
            "current_title": title_confidence,
        },
    }
