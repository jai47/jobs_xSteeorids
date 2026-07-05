"""
F06 — deterministic role archetype classifier (title-first, description fallback).
"""

from __future__ import annotations

import re
from typing import Callable

ARCHETYPES = (
    "ml_engineering",
    "llm_ai_engineering",
    "data_science",
    "data_engineering",
    "backend",
    "fullstack_frontend",
    "devops_platform",
    "product_management",
    "solutions_devrel",
    "other",
)

Pattern = str | re.Pattern[str]


def _match(text: str, patterns: list[Pattern]) -> bool:
    lowered = text.lower()
    for pattern in patterns:
        if isinstance(pattern, re.Pattern):
            if pattern.search(lowered):
                return True
        elif pattern.lower() in lowered:
            return True
    return False


# Ordered rule list — first match wins (precedence documented in code).
_RULES: list[tuple[str, list[Pattern], list[Pattern]]] = [
    (
        "llm_ai_engineering",
        [
            r"\bllm\b",
            r"\blarge language model",
            r"\bgenerative ai\b",
            r"\bgenai\b",
            r"\bprompt engineer",
            r"\bai engineer\b",
            r"\bfoundation model",
        ],
        [r"\bllm\b", r"\bgenerative ai\b", r"\brag\b"],
    ),
    (
        "ml_engineering",
        [
            r"\bmachine learning engineer",
            r"\bml engineer\b",
            r"\bapplied scientist\b",
            r"\bresearch engineer\b.*\bml\b",
            r"\bdeep learning engineer\b",
        ],
        [
            r"\bmachine learning\b",
            r"\bpytorch\b",
            r"\btensorflow\b",
            r"\bmodel training\b",
            r"\bml platform\b",
        ],
    ),
    (
        "data_science",
        [
            r"\bdata scientist\b",
            r"\bquantitative analyst\b",
            r"\bstatistician\b",
            r"\bresearch scientist\b.*\bdata\b",
        ],
        [r"\bdata science\b", r"\ba/b test", r"\bexperimentation\b", r"\bcausal inference\b"],
    ),
    (
        "data_engineering",
        [
            r"\bdata engineer\b",
            r"\banalytics engineer\b",
            r"\betl engineer\b",
            r"\bdata platform engineer\b",
        ],
        [r"\bdata pipeline\b", r"\bairflow\b", r"\bspark\b", r"\bdbt\b", r"\bdata warehouse\b"],
    ),
    (
        "devops_platform",
        [
            r"\bdevops\b",
            r"\bplatform engineer\b",
            r"\bsite reliability\b",
            r"\bsre\b",
            r"\binfrastructure engineer\b",
            r"\bcloud engineer\b",
            r"\bkubernetes\b",
        ],
        [r"\bterraform\b", r"\bci/cd\b", r"\bk8s\b", r"\bobservability\b"],
    ),
    (
        "product_management",
        [
            r"\bproduct manager\b",
            r"\bproduct owner\b",
            r"\btechnical product manager\b",
            r"\btpm\b",
        ],
        [r"\bproduct roadmap\b", r"\bproduct strategy\b", r"\buser research\b"],
    ),
    (
        "solutions_devrel",
        [
            r"\bdeveloper advocate\b",
            r"\bdevrel\b",
            r"\bsolutions architect\b",
            r"\bsolutions engineer\b",
            r"\btechnical evangelist\b",
            r"\bcustomer engineer\b",
        ],
        [r"\bdeveloper relations\b", r"\btechnical workshops\b"],
    ),
    (
        "fullstack_frontend",
        [
            r"\bfull[\s-]?stack\b",
            r"\bfrontend engineer\b",
            r"\bfront-end engineer\b",
            r"\breact engineer\b",
            r"\bui engineer\b",
        ],
        [r"\breact\b", r"\bvue\b", r"\bangular\b", r"\btypescript\b", r"\bfrontend\b"],
    ),
    (
        "backend",
        [
            r"\bbackend engineer\b",
            r"\bback-end engineer\b",
            r"\bsoftware engineer\b",
            r"\bapi engineer\b",
            r"\bservices engineer\b",
        ],
        [r"\bmicroservices\b", r"\brest api\b", r"\bpostgresql\b", r"\bbackend\b"],
    ),
]

_COMPILED_RULES: list[tuple[str, list[Pattern], list[Pattern]]] = [
    (
        archetype,
        [re.compile(p, re.I) if p.startswith(r"\b") or "\\b" in p else p for p in title_patterns],
        [re.compile(p, re.I) if p.startswith(r"\b") or "\\b" in p else p for p in desc_patterns],
    )
    for archetype, title_patterns, desc_patterns in _RULES
]


def classify_archetype(title: str | None, description: str | None = None) -> str:
    """Return one canonical archetype for a job posting."""
    title_text = (title or "").strip()
    desc_text = (description or "").strip()

    for archetype, title_patterns, desc_patterns in _COMPILED_RULES:
        if title_text and _match(title_text, title_patterns):
            return archetype

    for archetype, _title_patterns, desc_patterns in _COMPILED_RULES:
        if desc_text and _match(desc_text, desc_patterns):
            return archetype

    return "other"
