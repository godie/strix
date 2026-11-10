"""Unified subscription-vs-API-key resolution.

Both subscription backends, ChatGPT (``codex``) and Claude Code, bill at a
flat rate, so a run on either reports ``auth_mode="subscription"`` and zero
per-token cost. Four call sites ask this question (report state, scan setup,
usage viewer, resumed-run detection); they all go through here so a third
subscription backend is a one-line change, not a four-place hunt.
"""

from __future__ import annotations

from strix.config import claude_code, codex, freebuff


def auth_mode(model_name: str | None) -> str:
    """``"subscription"`` if the model runs at a genuine $0 flat rate, else ``"api_key"``.

    ChatGPT OAuth can only produce a subscription session, so its prefix alone is
    conclusive. Claude Code, though, can be signed in on either a subscription or
    an ``ANTHROPIC_API_KEY``; a ``claude-code/`` run on an API key meters normally,
    so the prefix is not enough, consult the actual session. Classifying an
    API-key run as a subscription would force its cost to $0 and defeat the budget
    guard on a metered scan.
    """
    if codex.subscription_model(model_name):
        return "subscription"
    if freebuff.freebuff_model(model_name):
        # The free tier is ad-supported and flat-rate, so a run on it costs $0
        # like the other subscription backends. It cannot start yet (the CLI has
        # no non-interactive mode), but calling it metered would be wrong the
        # moment it can, and would put a price on a free plan.
        return "subscription"
    if claude_code.claude_code_model(model_name):
        return "subscription" if claude_code.session_state() == "subscription" else "api_key"
    return "api_key"


def is_subscription(model_name: str | None) -> bool:
    return auth_mode(model_name) == "subscription"


def label(model_name: str | None) -> str:
    """Human-facing name for the subscription backend a model runs on.

    Falls back to a generic label when the model matches neither backend (the
    caller should only show this for a subscription run in the first place).
    """
    if claude_code.claude_code_model(model_name):
        return "Claude subscription"
    if freebuff.freebuff_model(model_name):
        return "Freebuff (free plan)"
    if codex.subscription_model(model_name):
        return "ChatGPT subscription"
    return "subscription"
