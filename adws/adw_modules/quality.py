"""Deterministic lint, typecheck, build, and test blocks.

A known command is not a judgement call. Anything whose invocation you can write
down belongs here as code — it runs in milliseconds, costs nothing, and returns
the same answer every time. Agents are for the parts that need reading and
deciding.

╔══════════════════════════════════════════════════════════════════════════════╗
║  REPLACE THE PLACEHOLDER COMMANDS BELOW.                                     ║
║                                                                              ║
║  Every block ships as an `echo` that exits 0 and announces it is fake. They   ║
║  are placeholders on purpose: a stamped repo has no way to guess your test    ║
║  runner, and a wrong-but-plausible command that silently passes is worse      ║
║  than one that says so out loud.                                             ║
║                                                                              ║
║  For each block you want: swap `_placeholder(...)` for the real argv, e.g.    ║
║      argv=["bun", "test", "apps/web/server.test.ts"]                         ║
║      argv=["uv", "run", "pytest", "-q"]                                      ║
║      argv=["npm", "run", "lint"]                                             ║
║  Delete the blocks you don't need, and drop them from run_quality()'s list.   ║
║                                                                              ║
║  Two rules when you write the real command:                                  ║
║    1. argv LIST, never a shell string — no quoting bugs, no shell injection.  ║
║    2. Call binaries by BARE NAME. These blocks inherit the operator's         ║
║       environment (see utils.operator_env), so `bun`, `uv`, `pytest` resolve  ║
║       exactly as they do in their terminal. Never hard-code an absolute path  ║
║       like /Users/you/.bun/bin/bun — that bakes your machine into the trace.  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable

from .data_types import (EventRecord, QualityCheckResult, QualityCheckSpec, QualityResult,
                         VerifyOutput)
from .detect import detect_checks
from .utils import now_iso, operator_env

# How much of a failing command's output rides back inside the envelope. Enough
# for a builder to act on without opening the artifact; bounded so a runaway
# stack trace can't swamp the next agent's context.
TAIL_CHARS = 4_000


PLACEHOLDER_MARK = "PLACEHOLDER"


def _placeholder(name: str) -> list[str]:
    """A command that does nothing and admits it. Replace every call to this."""
    return ["echo", f"{PLACEHOLDER_MARK} {name}: edit adws/adw_modules/quality.py and "
                    f"replace this echo with the real {name} command"]


def is_placeholder(spec: QualityCheckSpec) -> bool:
    """Is this check an `echo` that passes no matter what the code does?"""
    return spec.argv[:1] == ["echo"] and any(PLACEHOLDER_MARK in arg for arg in spec.argv)


def unconfigured(run) -> list[str]:
    """Which quality checks would pass on any code at all.

    A placeholder check does not fail loudly — it goes GREEN, every time, and a
    green check reads as a safety net that is not there. That is the worst
    shape a defect can take in this system: the run reports success, the
    engineer trusts it, and nothing anywhere says the net is missing.

    A workflow that depends on real verification calls this first and refuses,
    naming the checks to configure. Better to stop with a list than to build on
    four checks that were never going to fail.
    """
    return [spec.name for spec in _specs(run) if is_placeholder(spec)]


def _check_dir(run, name: str) -> Path:
    seq = run.phases[-1].seq if run.phases else 0
    path = run.context_handoff_dir / "quality" / f"{seq:02d}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(spec: QualityCheckSpec, run) -> QualityCheckResult:
    phase = run.phases[-1]
    output_dir = _check_dir(run, spec.name)
    output_artifact = output_dir / "command.log"
    command = shlex.join(spec.argv)
    env = operator_env()             # the engineer's own shell environment

    run.console.note(f"quality {spec.name}: {command}")
    started_at = now_iso()
    clock = time.monotonic()
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=run.repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode = 124
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + f"\nTimed out after {spec.timeout_seconds}s."
    except OSError as error:
        # A missing binary lands here as exit 127 with the real message — no
        # pre-flight probe needed, and none wanted.
        returncode = 127
        stderr = str(error)

    duration = time.monotonic() - clock
    output_artifact.write_text(
        f"$ {command}\nexit: {returncode}\nduration_seconds: {duration:.3f}\n"
        f"\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
    )
    passed = returncode == 0
    run.tracer.event(EventRecord(
        adw_id=run.adw_id,
        phase_id=phase.phase_id,
        type="tool_call",
        name=f"quality:{spec.name}",
        payload={
            "area": spec.area,
            "operation": spec.operation,
            "command": command,
            "returncode": returncode,
            "passed": passed,
            "output_artifact": str(output_artifact),
        },
        started_at=started_at,
        ended_at=now_iso(),
    ))
    run.console.note(
        f"quality {spec.name}: {'passed' if passed else 'failed'} "
        f"(exit {returncode}, {duration:.1f}s)"
    )
    return QualityCheckResult(
        name=spec.name,
        area=spec.area,
        operation=spec.operation,
        command=command,
        returncode=returncode,
        passed=passed,
        duration_seconds=duration,
        output_artifact=str(output_artifact),
        output_tail=(stdout + stderr)[-TAIL_CHARS:],
    )


# ── Blocks ────────────────────────────────────────────────────────────────────
# Replace every argv below. See the banner at the top of this file.

# Override here to pin a command by hand. Anything not in this dictionary is
# DETECTED from the repository itself (detect.py) — the engineer should not have
# to write out the test command of a project that already announces it.
OVERRIDES: dict[str, list[str]] = {
    # This project exposes its JavaScript package below the repository root,
    # so automatic detection cannot see its package.json. The build includes
    # the Vue typecheck and is the project-wide check every ticket must pass.
    "test": ["bun", "run", "--cwd=apps/visualizer", "build"],
}

# The FACTORY'S OWN suite, which detection does not find (and must not find:
# `adws` is excluded precisely so the factory is not mistaken for the project).
# Running it here is what stops a fix to the loop, the graph or the worktree from
# shipping broken without anyone noticing — and those three decide the order and
# touch git.
FACTORY_TESTS = ["python3", "-m", "unittest", "discover", "-s", "adws/adw_tests", "-t", "adws"]

# `test` always appears: undetected it becomes a placeholder, and a placeholder
# makes the run refuse. The others exist only if the repo has them — demanding a
# typecheck from a project without types would only teach the engineer to pass
# `--no-checks`.
_OPERATION = {"test": "build", "lint": "lint", "typecheck": "typecheck", "build": "build"}
_TIMEOUT = {"test": 600}


def _specs(run) -> list[QualityCheckSpec]:
    """Every check this project declares, WITHOUT running any of them.

    Split out from the block functions so `unconfigured()` can ask what is
    configured without paying for four subprocesses to find out — and so there
    is exactly one place where a check is declared.
    """
    argvs = {**detect_checks(run.repo_root), **OVERRIDES}
    names = ["test"] + [n for n in ("lint", "typecheck", "build") if n in argvs]
    return [
        QualityCheckSpec(
            name=name,
            area="backend",
            operation=_OPERATION[name],
            argv=argvs.get(name) or _placeholder(name),
            timeout_seconds=_TIMEOUT.get(name, 120),
        )
        for name in names
    ]


def _spec(run, name: str) -> QualityCheckSpec:
    for spec in _specs(run):
        if spec.name == name:
            return spec
    # `next()` without a default raised StopIteration, whose str() is EMPTY — the
    # phase failed and the trace recorded `error: ""`. An error without a message
    # is worse than an error: it burns the time of whoever is looking without
    # pointing at anything.
    available = ", ".join(s.name for s in _specs(run)) or "none"
    raise RuntimeError(
        f"the check '{name}' does not exist in this project (detected: {available}). "
        f"Either detection did not recognise it, or it does not apply here.")


def test(run) -> QualityCheckResult:
    """Run the project's test suite. The highest-value block to wire up first."""
    return _run(_spec(run, "test"), run)


def lint(run) -> QualityCheckResult:
    return _run(_spec(run, "lint"), run)


def typecheck(run) -> QualityCheckResult:
    return _run(_spec(run, "typecheck"), run)


def build(run) -> QualityCheckResult:
    return _run(_spec(run, "build"), run)


def run_tests(run) -> QualityResult:
    """The test suite alone, as a QualityResult — the deterministic test phase.

    This is what replaces a `tester` agent once the command is written down. An
    agent rediscovering the runner on every run costs a fortune to learn what a
    subprocess already knows; the repair loop is unchanged, because a failure
    still reaches the builder through `as_envelope` below.
    """
    check = test(run)
    failures = ([] if check.passed else
                [f"{check.name}: `{check.command}` exited {check.returncode}\n"
                 f"{check.output_tail}".rstrip()])
    return QualityResult(passed=check.passed, checks=[check], failures=failures,
                         artifacts=[check.output_artifact])


def as_envelope(result: QualityResult, what: str) -> VerifyOutput:
    """Wrap a deterministic result so an agent can be handed it directly.

    Agents hand each other typed envelopes; code blocks return QualityResult.
    This is the adapter, so a failing lint or test run flows back into the
    builder through exactly the same door an agent's report would — the ADW
    script is the only thing that knows the difference.
    """
    return VerifyOutput(
        status="success" if result.passed else "fail",
        summary=(f"{what}: all {len(result.checks)} check(s) passed" if result.passed
                 else f"{what}: {len(result.failures)} of {len(result.checks)} check(s) failed"),
        artifacts=result.artifacts,
        notes_for_next_agent=("" if result.passed else
                              "Fix every failure below. The output is verbatim from the "
                              "command — trust it over any summary."),
        passed=result.passed,
        failures=result.failures,
    )


def run_quality(run) -> QualityResult:
    """Run every block and collect ALL failures — one pass tells you everything.

    Ordering contract for the caller: a failing block does NOT fail the phase.
    The runner did its job; the CODE is what failed. Hand this result to the
    builder and let the bounded repair loop decide the run's fate.
    """
    # Runs what THIS project declares, not a fixed list of four.
    #
    # It used to be a fixed `[test, lint, typecheck, build]`, from when all four
    # always existed as placeholders. Since detection started including only what
    # the repository announces, calling `lint()` in a project without lint blew up
    # — and blew up without a message, bringing the phase down after the real
    # checks had passed.
    checks = [_run(spec, run) for spec in _specs(run)]
    # A failure is the command, its exit code, and what it actually printed —
    # everything a builder needs to repair without opening a log or being told
    # what the error "means" by a parser that guessed.
    failures = [
        f"{check.name}: `{check.command}` exited {check.returncode}\n{check.output_tail}".rstrip()
        for check in checks if not check.passed
    ]
    return QualityResult(
        passed=not failures,
        checks=checks,
        failures=failures,
        artifacts=[check.output_artifact for check in checks],
    )
