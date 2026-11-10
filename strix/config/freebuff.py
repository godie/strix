"""Freebuff backend: the ``freebuff/<model>`` prefix and its headless-mode gate.

Freebuff's CLI is a TUI. It has no non-interactive mode: ``-p`` and ``--print``
are unknown options and its stdout carries no machine-readable events, so there
is nothing for a transport to drive yet. The gap is tracked upstream, at
https://github.com/CodebuffAI/freebuff/issues/947.

Strix still claims the ``freebuff/`` prefix for one reason: someone who types it
should get a single actionable preflight stop that says why the run cannot start
and what to use meanwhile, instead of a confusing LiteLLM failure for a model
name no provider knows. When the CLI ships the mode, the transport lands beside
``claude_process`` and this module grows an argv builder; the probe below is what
will tell it the environment is finally ready.
"""

from __future__ import annotations

import logging

from strix.config import code_agent_cli


logger = logging.getLogger(__name__)

PROVIDER = "freebuff"
SUBSCRIPTION_PREFIX = "freebuff/"

SPEC = code_agent_cli.CodeAgentCli(
    provider=PROVIDER,
    binary="freebuff",
    display_name="Freebuff",
    # No version floor yet: there is no contract to be too old for. The gate is
    # the headless mode itself, which is what headless_flags probes for.
    headless_flags=("--print", "-p"),
    headless_tracker="https://github.com/CodebuffAI/freebuff/issues/947",
)


def freebuff_model(model_name: str | None) -> str | None:
    """The model slug behind a ``freebuff/<model>`` STRIX_LLM, or None.

    Mirrors :func:`strix.config.claude_code.claude_code_model`: strip,
    case-insensitive prefix match, empty slug returns None.
    """
    name = (model_name or "").strip()
    if not name.lower().startswith(SUBSCRIPTION_PREFIX):
        return None
    return name[len(SUBSCRIPTION_PREFIX) :] or None


def binary_path() -> str | None:
    """Absolute path to the ``freebuff`` binary on PATH, or None."""
    return code_agent_cli.binary_path(SPEC)


def version() -> str | None:
    """The ``freebuff --version`` string, or None when the probe failed."""
    completed = code_agent_cli.probe(SPEC, ["--version"])
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def help_text() -> str | None:
    """``freebuff --help`` output, or None when the probe failed."""
    completed = code_agent_cli.probe(SPEC, ["--help"])
    if completed is None or completed.returncode != 0:
        return None
    return completed.stdout


def headless_state() -> str:
    """``"ok"``, ``"unsupported"``, or ``"unknown"`` when ``--help`` failed."""
    return code_agent_cli.headless_state(SPEC, help_text())


def problem() -> str | None:
    """Why a ``freebuff/`` run cannot start on this host, or None when it can.

    Ordered from the cause the user can fix locally to the one only upstream can
    (missing binary, an unreadable probe, then the missing mode itself), so the
    message never blames Freebuff for an installation problem.
    """
    if binary_path() is None:
        return (
            "The `freebuff` CLI isn't on PATH. Install it on this host, then run `freebuff login`."
        )
    state = code_agent_cli.version_state(SPEC, version())
    if state == "unknown":
        return (
            "Couldn't read a version from the Freebuff CLI on PATH, so it may not be "
            "installed correctly. Check that `freebuff --version` runs on this host."
        )
    headless = headless_state()
    if headless == "unsupported":
        return (
            "The Freebuff CLI has no non-interactive mode (no `--print`), so Strix "
            f"can't drive it yet; the gap is tracked at {SPEC.headless_tracker}. "
            "Use `claude-code/<model>`, `chatgpt/<model>`, or a metered provider until then."
        )
    if headless == "unknown":
        return (
            "Couldn't tell whether the Freebuff CLI has a non-interactive mode. Check "
            "that `freebuff --help` runs on this host."
        )
    return None


def unavailable_error(model_name: str | None) -> str:
    """The error for a ``freebuff/`` model that reaches the model factory."""
    reason = problem()
    if reason is None:
        # The CLI advertises a print mode but this build has no transport for it
        # yet, which is a different gap from the upstream one and says so.
        return (
            f"STRIX_LLM={model_name} resolves to the Freebuff backend, which this build "
            "has no transport for yet."
        )
    return f"STRIX_LLM={model_name} cannot run on Freebuff yet. {reason}"
