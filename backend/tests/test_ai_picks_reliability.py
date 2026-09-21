"""Catch-up decisions, prompt/tool parity, and freshness rules for AI picks.

Covers Final Plan sections 1 (reliability) and 5 (tests). DB-touching paths
are exercised through fakes; the live scheduler behavior is asserted via the
pure decision helpers with explicit dates.
"""
from datetime import datetime, timezone

from app.services.ai_chat_service import BLM_TOOLS
from app.workers import ai_picks_worker as w


# --- Catch-up decision matrix (§1.1-1.2, §5) ---------------------------------

def test_morning_due_when_never_succeeded():
    assert w._morning_due(None, "2026-09-21") is True


def test_morning_due_when_failed_yesterday_but_not_today():
    assert w._morning_due("2026-09-20", "2026-09-21") is True


def test_morning_not_due_when_succeeded_today():
    assert w._morning_due("2026-09-21", "2026-09-21") is False


def test_evening_due_past_close_with_unevaluated_picks():
    assert w._evening_due(None, "2026-09-21", True, True) is True


def test_evening_not_due_without_picks():
    # App was off all day: morning runner covers it, skip silently.
    assert w._evening_due(None, "2026-09-21", False, True) is False


def test_evening_not_due_before_close():
    assert w._evening_due(None, "2026-09-21", True, False) is False


def test_evening_not_due_when_already_evaluated():
    assert w._evening_due("2026-09-21", "2026-09-21", True, True) is False


def test_today_ist_str_and_past_market_hours():
    # 10:00 UTC = 15:30 IST -> exactly at close boundary
    at_close = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
    assert w._today_ist_str(at_close) == "2026-09-21"
    assert w._past_market_hours(at_close) is True
    morning = datetime(2026, 9, 21, 2, 0, tzinfo=timezone.utc)  # 07:30 IST
    assert w._past_market_hours(morning) is False
    # 18:30 UTC = midnight IST next day
    midnight = datetime(2026, 9, 21, 18, 30, tzinfo=timezone.utc)
    assert w._today_ist_str(midnight) == "2026-09-22"


# --- Prompt/tool parity: every tool named in prompts must be callable (§4) ---

def _prompt_tool_names():
    import re
    names = set()
    for prompt in (w.HUNTER_PROMPT, w.VERIFIER_PROMPT, w.EVALUATOR_PROMPT):
        names.update(re.findall(r"`([a-z][a-z0-9_]+)`", prompt))
    return names


def test_prompt_tools_all_advertised():
    """Guards the get_upcoming_events-class mismatch: named => in BLM_TOOLS."""
    advertised = {t["function"]["name"] for t in BLM_TOOLS}
    # Non-tool backtick terms used prose-wise in prompts (tiers, field names).
    prose = {"low", "medium", "high", "last_updated"}
    missing = {n for n in _prompt_tool_names() - prose if n not in advertised}
    assert not missing, f"prompt names tools not in BLM_TOOLS: {missing}"


def test_events_tools_advertised():
    advertised = {t["function"]["name"] for t in BLM_TOOLS}
    assert "get_upcoming_events" in advertised
    assert "get_recent_announcements" in advertised


# --- Freshness rule wording present in all three prompts (§3) -----------------

def test_freshness_rules_present():
    for prompt in (w.HUNTER_PROMPT, w.VERIFIER_PROMPT, w.EVALUATOR_PROMPT):
        assert "last_updated" in prompt
        assert "48 hours" in prompt


def test_hunter_owns_news_fetching():
    assert "get_global_news" in w.HUNTER_PROMPT
    assert "get_company_news" in w.HUNTER_PROMPT
    assert "NO news" in w.HUNTER_PROMPT


def test_verifier_repulls_news_independently():
    assert "get_company_news" in w.VERIFIER_PROMPT
    assert "never trust" in w.VERIFIER_PROMPT.lower()
