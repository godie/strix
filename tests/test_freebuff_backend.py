"""Freebuff backend: prefix parsing and the headless-mode gate.

Freebuff's CLI has no non-interactive mode, so a ``freebuff/...`` model must stop
at preflight with one actionable message. These tests pin the gate (and the fact
that it opens on its own once the CLI advertises ``--print``) without needing the
CLI installed: every probe is answered from a recorded ``--help``.
"""

from __future__ import annotations

import subprocess

import pytest
from rich.console import Console

from strix.config import code_agent_cli, freebuff, subscription
from strix.config.models import StrixProvider, routes_through_litellm
from strix.interface import environment


# The real `freebuff --help` of v0.2.36: no -p, no --print, no output format.
HELP_WITHOUT_PRINT = """Usage: freebuff [options] [command]

Freebuff - Free AI coding assistant

Arguments:
  command                       Command to run: login, or doctor to check this
                                computer for common problems (choices: "login",
                                "doctor")

Options:
  -v, --version                 Print the CLI version
  --continue [conversation-id]  Continue from a previous conversation
  --cwd <directory>             Set the working directory (default: current
                                directory)
  --trust-agents                Load this repository's .agents files and
                                mcp.json without asking (for CI)
  -h, --help                    Show this help message
"""

HELP_WITH_PRINT = HELP_WITHOUT_PRINT.replace(
    "  -h, --help                    Show this help message",
    "  -p, --print                   Print the reply and exit\n"
    "  -h, --help                    Show this help message",
)


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["freebuff"], returncode=0, stdout=stdout, stderr="")


def _install_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present: bool = True,
    version: str | None = "0.2.36\n",
    help_text: str | None = HELP_WITHOUT_PRINT,
) -> None:
    """Answer every probe from the given recordings, as an installed CLI would."""
    monkeypatch.setattr(
        freebuff, "binary_path", lambda: "/usr/local/bin/freebuff" if present else None
    )

    def _probe(
        _spec: object, args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str] | None:
        if args == ["--version"]:
            return None if version is None else _completed(version)
        if args == ["--help"]:
            return None if help_text is None else _completed(help_text)
        raise AssertionError(f"unexpected probe: {args}")

    monkeypatch.setattr(freebuff.code_agent_cli, "probe", _probe)


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("freebuff/base", "base"),
        ("FREEBUFF/base", "base"),
        ("  freebuff/base  ", "base"),
        ("freebuff/", None),
        ("claude-code/claude-opus-4-8", None),
        ("chatgpt/gpt-5.4", None),
        ("", None),
        (None, None),
    ],
)
def test_freebuff_model(model: str | None, expected: str | None) -> None:
    assert freebuff.freebuff_model(model) == expected


def test_missing_binary_says_install_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cli(monkeypatch, present=False)
    problem = freebuff.problem()
    assert problem is not None
    assert "isn't on PATH" in problem
    assert "freebuff login" in problem


def test_missing_print_mode_names_the_upstream_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    # The whole point of claiming a prefix Strix cannot drive: one message that
    # says why, where it is tracked, and what to use meanwhile.
    _install_cli(monkeypatch)
    assert freebuff.headless_state() == "unsupported"
    problem = freebuff.problem()
    assert problem is not None
    assert "no `--print`" in problem
    assert freebuff.SPEC.headless_tracker is not None
    assert freebuff.SPEC.headless_tracker in problem
    assert "claude-code/<model>" in problem


def test_print_mode_opens_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Nothing here hardcodes "Freebuff is unavailable": the gate is a probe, so it
    # lifts by itself on the release that ships the mode.
    _install_cli(monkeypatch, help_text=HELP_WITH_PRINT)
    assert freebuff.headless_state() == "ok"
    assert freebuff.problem() is None


def test_unreadable_help_is_unknown_not_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    # "Upgrade your CLI" is the wrong advice when the probe itself did not run.
    _install_cli(monkeypatch, help_text=None)
    assert freebuff.headless_state() == "unknown"
    problem = freebuff.problem()
    assert problem is not None
    assert "Couldn't tell" in problem
    assert "tracked at" not in problem


def test_unreadable_version_is_reported_before_the_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cli(monkeypatch, version=None)
    problem = freebuff.problem()
    assert problem is not None
    assert "Couldn't read a version" in problem


def test_long_options_do_not_satisfy_a_short_flag() -> None:
    # `-h, --help` must not count as `-p`, or every CLI would look drivable.
    assert code_agent_cli.flags_present("-h, --help", ("-p",)) is False
    assert code_agent_cli.flags_present("-p, --print", ("-p",)) is True
    assert code_agent_cli.flags_present("--print", ("--print",)) is True


def test_subscription_treats_freebuff_as_flat_rate() -> None:
    # The free tier is ad-supported, so a run on it is $0 like the other
    # subscription backends, not metered against an API key.
    assert subscription.auth_mode("freebuff/base") == "subscription"
    assert subscription.is_subscription("freebuff/base") is True
    assert subscription.label("freebuff/base") == "Freebuff (free plan)"


def test_freebuff_never_routes_through_litellm() -> None:
    # It is not an HTTP model; letting LiteLLM try would bury the real reason.
    assert routes_through_litellm("freebuff/base") is False


def test_model_factory_refuses_a_freebuff_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cli(monkeypatch)
    with pytest.raises(RuntimeError) as exc:
        StrixProvider().get_model("freebuff/base")
    assert "freebuff/base" in str(exc.value)
    assert "no `--print`" in str(exc.value)


def test_preflight_exits_while_the_gate_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cli(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        environment._validate_freebuff(Console(), "freebuff/base")
    assert exc.value.code == 1


def test_preflight_passes_once_the_mode_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_cli(monkeypatch, help_text=HELP_WITH_PRINT)
    # No SystemExit means the preflight returned cleanly.
    environment._validate_freebuff(Console(), "freebuff/base")
