"""Tests for billing context helpers."""
from utils.billing_plans import get_public_plans, plan_effective_per_user


def test_public_plans_include_effective_per_user():
    plans = get_public_plans()
    starter = next(p for p in plans if p["id"] == "starter")
    assert starter["effective_per_user_monthly"] == plan_effective_per_user("starter")
    assert starter["effective_per_user_monthly"] == 2.45  # 49/20


def test_enterprise_no_effective_price():
    assert plan_effective_per_user("enterprise") is None
