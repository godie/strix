"""Transport-agnostic probing for code-agent CLI backends.

Two Strix backends drive a coding agent installed on the host instead of an HTTP
model: Claude Code (``claude-code/``) and Freebuff (``freebuff/``). Their argv,
wire formats and quota semantics differ, but the questions asked before a run do
not: is the binary on ``PATH``, is it new enough to drive, and does it offer a
non-interactive mode at all. Those probes live here, so a new backend is a
:class:`CodeAgentCli` record plus its own small adapter rather than another copy
of the same subprocess plumbing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass


PROBE_TIMEOUT_S = 8


@dataclass(frozen=True)
class CodeAgentCli:
    """What Strix needs to know about a coding-agent CLI in order to probe it.

    ``headless_flags`` is read out of ``--help`` before anything is spawned for
    real: a CLI with no non-interactive mode cannot be driven at all, whatever
    version it reports, so that gap has to be its own answer rather than a
    runtime failure halfway through a scan.
    """

    provider: str
    binary: str
    display_name: str
    min_version: tuple[int, int, int] | None = None
    headless_flags: tuple[str, ...] = ()
    headless_tracker: str | None = None


def binary_path(spec: CodeAgentCli) -> str | None:
    """Absolute path to the CLI's binary on ``PATH``, or None."""
    return shutil.which(spec.binary)


def run_cli(
    binary: str, args: list[str], *, timeout: float = PROBE_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """Run one probe against an installed CLI.

    UTF-8 is pinned because ``text=True`` otherwise decodes with the host locale
    codec: the CLIs emit UTF-8, and a console on a non-UTF-8 code page (cp1252,
    cp932) would raise ``UnicodeDecodeError`` straight out of a probe that is
    only supposed to answer a question.
    """
    return subprocess.run(  # noqa: S603  # trusted binary, fixed argv, no shell
        [binary, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def probe(
    spec: CodeAgentCli, args: list[str], *, timeout: float = PROBE_TIMEOUT_S
) -> subprocess.CompletedProcess[str] | None:
    """:func:`run_cli` for ``spec``, or None when the CLI cannot be executed."""
    binary = binary_path(spec)
    if binary is None:
        return None
    try:
        return run_cli(binary, args, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def parse_version(raw: str | None) -> tuple[int, int, int] | None:
    """``"2.1.234 (Claude Code)"`` as ``(2, 1, 234)``, or None when unreadable."""
    if not raw:
        return None
    token = raw.strip().split()[0]
    try:
        nums = tuple(int(part) for part in token.split(".")[:3])
    except ValueError:
        return None
    padded = (*nums, 0, 0)[:3]
    return (padded[0], padded[1], padded[2])


def version_floor(spec: CodeAgentCli) -> str:
    """The minimum version, formatted for a message, or ``"(any)"``."""
    if spec.min_version is None:
        return "(any)"
    return ".".join(str(part) for part in spec.min_version)


def version_state(spec: CodeAgentCli, raw: str | None) -> str:
    """``"ok"``, ``"too_old"``, or ``"unknown"`` when the probe itself failed.

    The three are kept apart because "update your CLI" is the wrong thing to
    tell someone whose binary did not run at all, and both of those reach here
    as a missing version string.
    """
    parsed = parse_version(raw)
    if parsed is None:
        return "unknown"
    if spec.min_version is None:
        return "ok"
    return "ok" if parsed >= spec.min_version else "too_old"


def flags_present(help_text: str, flags: tuple[str, ...]) -> bool:
    """Whether ``--help`` output advertises any of ``flags`` as a real option.

    Matched on token boundaries, so ``--help`` never counts as ``-p`` and a flag
    mentioned inside prose is not mistaken for one the parser accepts.
    """
    if not help_text:
        return False
    return any(
        re.search(r"(?<![\w-])" + re.escape(flag) + r"(?![\w-])", help_text) for flag in flags
    )


def headless_state(spec: CodeAgentCli, help_text: str | None) -> str:
    """``"ok"``, ``"unsupported"``, or ``"unknown"`` when ``--help`` failed.

    A spec with no ``headless_flags`` is never gated here: its transport carries
    its own version floor instead, which is the check that actually matters for
    it.
    """
    if not spec.headless_flags:
        return "ok"
    if help_text is None:
        return "unknown"
    return "ok" if flags_present(help_text, spec.headless_flags) else "unsupported"
