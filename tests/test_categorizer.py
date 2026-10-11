from artemis.db.models import Category, MerchantRule
from artemis.domain.categorizer import (
    categorize,
    match_rule,
    normalize_merchant,
    normalize_text,
    rule_from_merchant,
)


def _cats():
    return [
        Category(id=1, owner_id="owner", name="Groceries", kind="expense"),
        Category(id=2, owner_id="owner", name="Dining", kind="expense"),
    ]


def test_normalize_text():
    assert normalize_text("Whole Foods #123", "Purchase!") == "whole foods 123 purchase"
    assert normalize_merchant("whole foods market") == "Whole Foods Market"
    assert normalize_merchant(None) is None


def test_match_rule_priority_wins():
    rules = [
        MerchantRule(owner_id="owner", pattern="whole foods", category_id=1, priority=50, id=1),
        MerchantRule(owner_id="owner", pattern="foods", category_id=2, priority=100, id=2),
    ]
    match = match_rule("WHOLE FOODS #12", rules, {1: _cats()[0], 2: _cats()[1]})
    assert match.source == "rule"
    assert match.category_name == "Groceries"


def test_match_rule_substring():
    rules = [MerchantRule(owner_id="owner", pattern="cafe", category_id=2, priority=100, id=1)]
    match = match_rule("Cafe Rio lunch", rules, {2: _cats()[1]})
    assert match.category_id == 2


def test_no_match():
    match = match_rule("Random shop", [], {})
    assert match.source == "none"
    assert match.category_id is None


def test_categorize_uses_merchant_and_description():
    rules = [MerchantRule(owner_id="owner", pattern="rio", category_id=2, priority=100, id=1)]
    match = categorize(
        merchant="Cafe", description="Rio lunch", rules=rules, categories=_cats()
    )
    assert match.category_name == "Dining"


def test_rule_from_merchant():
    assert rule_from_merchant("Whole Foods Market", None) == "whole foods"
    assert rule_from_merchant(None, "Netflix.com subscription") == "netflix com"
    assert rule_from_merchant(None, None) is None
    assert rule_from_merchant("A", None) is None
