"""Hybrid categorization: merchant/keyword rules first, LLM fallback second.

This module is pure and synchronous. It decides *whether* a rule matches; the
LLM fallback is driven by the caller (the transactions agent / ledger service),
which can then persist the LLM's answer back as a new rule via
:func:`rule_from_merchant`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from artemis.db.models import Category, MerchantRule

_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"[^a-z0-9 &]+")


@dataclass(frozen=True, slots=True)
class CategoryMatch:
    category_id: int | None
    category_name: str | None
    source: str  # "rule" | "none"
    pattern: str | None = None


def normalize_text(*parts: str | None) -> str:
    """Lower-case, collapse whitespace, and drop punctuation from free text."""
    joined = " ".join(p for p in parts if p)
    joined = _NOISE_RE.sub(" ", joined.lower())
    return _WS_RE.sub(" ", joined).strip()


def normalize_merchant(merchant: str | None) -> str | None:
    if not merchant:
        return None
    return normalize_text(merchant).title() or None


def match_rule(
    text: str,
    rules: list[MerchantRule],
    categories_by_id: dict[int, Category],
) -> CategoryMatch:
    """Return the highest-priority matching rule's category, or ``none``.

    Rules are matched as case-insensitive substrings of ``text`` (the
    merchant + description). Lower ``priority`` wins.
    """
    haystack = normalize_text(text)
    for rule in sorted(rules, key=lambda r: (r.priority, r.id or 0)):
        needle = normalize_text(rule.pattern)
        if needle and needle in haystack:
            category = categories_by_id.get(rule.category_id)
            return CategoryMatch(
                category_id=category.id if category else None,
                category_name=category.name if category else None,
                source="rule",
                pattern=rule.pattern,
            )
    return CategoryMatch(category_id=None, category_name=None, source="none")


def categorize(
    *,
    merchant: str | None,
    description: str | None,
    rules: list[MerchantRule],
    categories: list[Category],
) -> CategoryMatch:
    """Rule-first categorization for one transaction."""
    text = f"{merchant or ''} {description or ''}"
    return match_rule(text, rules, {c.id: c for c in categories if c.id is not None})


def rule_from_merchant(merchant: str | None, description: str | None = None) -> str | None:
    """Derive a stable rule pattern (first one or two tokens) from a merchant.

    Used to persist an LLM categorization decision as a reusable keyword rule.
    """
    basis = normalize_text(merchant) or normalize_text(description)
    if not basis:
        return None
    tokens = [t for t in basis.split() if len(t) > 1]
    if not tokens:
        return None
    return " ".join(tokens[:2])
