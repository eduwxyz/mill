"""Run the ticket's acceptance criterion, and say what its exit status MEANT.

The same command is run twice in a run, and the two runs want opposite answers:

    red     before any implementation   →  it must FAIL
    verify  after                       →  it must PASS

So this module never returns "passed"; it returns whether the result matched
what was EXPECTED at that point. A criterion that passes before anything was
built has not succeeded — it has failed to discriminate, and the phase that
called it needs to hear that as a failure.

Running the command is a known operation, so it is code (SKILL.md hard rule 8),
and it reuses `quality`'s runner rather than growing a second subprocess path
with its own timeout and logging conventions.
"""

from __future__ import annotations

from .data_types import QualityCheckResult, QualityCheckSpec, QualityResult
from .quality import _run, as_envelope

# Generous: an acceptance criterion may boot a server or build a schema.
CRITERION_TIMEOUT_SECONDS = 300

# What the gatekeeper's contract asks for. It is not an execution ceiling — it
# is the point past which the run warns: a slow criterion is almost never slow
# out of rigour, it is slow because it is fabricating a scenario instead of
# exercising a behaviour.
LIMIT_SECONDS = 60


def run_criterion(run, command: list[str], name: str = "criterion",
                  timeout_seconds: int = CRITERION_TIMEOUT_SECONDS) -> QualityCheckResult:
    """Run the criterion's own argv. `passed` here still means exit 0."""
    # `area`/`operation` do not anticipate "test" — the literals are
    # frontend|backend and lint|typecheck|build. `quality.test()` works around it
    # the same way, so following the existing convention beats widening the type
    # and diverging from it.
    return _run(QualityCheckSpec(
        name=name,
        area="backend",
        operation="build",
        argv=command,
        timeout_seconds=timeout_seconds,
    ), run)


def is_weak(result: QualityCheckResult) -> bool:
    """Did the criterion pass BEFORE anything was implemented?

    That is the failure this whole phase exists to catch: a criterion that is
    already satisfied is not describing the work, and every green after it is
    worthless. Named for what it detects rather than the exit code, because
    `returncode == 0` reads like success right up until it isn't.
    """
    return result.passed


def weak_gate_correction(result: QualityCheckResult, ticket_excerpt: str = "") -> str:
    """What the gatekeeper is told when its criterion passed too early.

    It gets the OUTPUT, not just the verdict: "it passed" leaves the agent
    guessing which check was vacuous, and guessing costs another attempt.
    """
    lines = [
        "The criterion you wrote PASSED before any implementation existed.",
        "That means it does not discriminate what the ticket asked for — it was",
        "already satisfied by the repository as it stands.",
        "",
        "Rewrite it to exercise the behaviour that does NOT exist yet. If one of",
        "the ticket's checkboxes is already satisfied today, say so in `uncovered`",
        "instead of inventing a check for it.",
        "",
        f"$ {result.command}",
        f"exit {result.returncode}",
        "",
        "--- output ---",
        result.output_tail or "(no output)",
    ]
    if ticket_excerpt:
        lines += ["", "--- the ticket ---", ticket_excerpt]
    return "\n".join(lines)


def collect(*results: QualityCheckResult) -> QualityResult:
    """Fold check results into the aggregate the fix loop already speaks.

    `verify` runs the ticket's criterion AND the project's own checks, and the
    builder must see every failure from one pass — telling it about the
    criterion, watching it fix that, then telling it about lint would spend two
    attempts on one round of work.
    """
    checks = list(results)
    failures = [f"{c.name}: exit {c.returncode}\n{c.output_tail}"
                for c in checks if not c.passed]
    return QualityResult(
        passed=all(c.passed for c in checks),
        checks=checks,
        failures=failures,
        artifacts=[c.output_artifact for c in checks],
    )


__all__ = ["run_criterion", "is_weak", "weak_gate_correction", "collect", "as_envelope",
           "CRITERION_TIMEOUT_SECONDS", "LIMIT_SECONDS"]
