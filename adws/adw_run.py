#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Run — build one ticket behind a criterion that had to fail first.

Usage:
    uv run adws/adw_run.py <path/to/ticket.md> [--max-fix 3] [--config ...] [--adw-id a1b2c3d4]

Phases: engineer(request) -> gatekeeper -> code(red) -> builder
        -> code(verify) [-> builder(fix) -> code(verify) ... bounded]
        -> reviewer [-> builder(revise) -> code(reverify) ... bounded] -> git(commit)

TDD with the red enforced by code instead of by discipline. The criterion is
written before any implementation, run once to prove it FAILS, and only then is
anything built. Nobody has to be trusted to have written the test first: the
run measured it.

**`red` is the phase that earns the rest.** Without it, `verify` going green
proves only that some command exited zero — which a criterion that was vacuous
from the start also does. A criterion that passes before the work exists is not
describing the work, so the gatekeeper is sent back with the output, bounded.

There is no planner. The ticket arrived through research → architect → spec →
slicer, and a fifth pass renaming its files buys less than it costs — the
builder reads those files anyway before it can edit them.

It REFUSES to start while the project's quality checks are still placeholders,
because a placeholder check goes green on any code at all — a safety net that
reads as present and is not. `--no-checks` overrides, knowingly.

The commit takes ONLY the paths this run's agents changed — `permissions.enforce`
already knows them, because it compares the change set before and after every
call. The engineer's work in progress stays where it was.

The criterion is COMMITTED, and `tests/acceptance/` is protected from the
builder: it grades the work, so the one agent it grades cannot edit it. Each
finished ticket leaves its criterion behind as a guard, and the next ticket's
`verify` runs it too. That is how ticket 4 finds out it broke ticket 2 while
someone is still looking.
"""

import argparse
import sys
from pathlib import Path

from adw_modules import agents, criterion, frontier as F, gates, git_helper, quality, session
from adw_modules.data_types import (AgentCall, BuildOutput, CriterionOutput, PhaseParams,
                                    ReviewOutput)

REQUIRED_AGENTS = ["gatekeeper", "builder", "reviewer"]

ACCEPTANCE_DIR = Path("tests/acceptance")
MAX_WEAK_GATE_ATTEMPTS = 2      # the gatekeeper gets one rewrite, not an argument
MAX_FIX_LOOPS = 3
MAX_REVIEW_LOOPS = 2      # the reviewer sends back once; a second refusal goes to the engineer


def main(ticket_path: Path, max_fix: int = MAX_FIX_LOOPS, allow_placeholders: bool = False,
         config: str = "adws/adw_mill_config/mill.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    if not ticket_path.is_file():
        print(f"ticket not found: {ticket_path}", file=sys.stderr)
        return 1

    # REFUSE BEFORE SPENDING AN AGENT.
    #
    # A placeholder check does not fail loudly: it stays GREEN, always. And a
    # green check reads as a safety net — one that is not there. It is the worst
    # shape a defect can take here, because the run reports success, you trust
    # it, and nothing anywhere says the net does not exist.
    #
    # With `--no-checks` you take that on: only this ticket's acceptance
    # criterion holds, and nothing guards what the previous tickets built.
    missing = quality.unconfigured(run)
    if missing and not allow_placeholders:
        print(
            f"\nthese checks are still placeholders and would pass on any code at all:"
            f"\n  {', '.join(missing)}\n"
            f"\nconfigure each one's argv in adws/adw_modules/quality.py — `_specs()`."
            f"\nwithout them, only THIS ticket's acceptance criterion holds, and nothing"
            f"\nprotects what the previous tickets already built."
            f"\n\nto run anyway:  --no-checks\n",
            file=sys.stderr)
        return run.finish(accepted=False,
                          reason=f"checks not configured: {', '.join(missing)}")
    ticket = ticket_path.read_text(encoding="utf-8")
    script = ACCEPTANCE_DIR / f"{ticket_path.stem}{_suffix(run.repo_root)}"

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Take one ticket, and say where its criterion lands")) as ph:
        ph.log(ticket=str(ticket_path), criterion=str(script))

    # ── the criterion, and the proof that it discriminates ───────────────────
    spec = None
    for attempt in range(1, MAX_WEAK_GATE_ATTEMPTS + 1):
        with run.phase(PhaseParams(name=f"criterion_{attempt}", kind="agent", owner="gatekeeper",
                                   description="Make the ticket's checkboxes executable while "
                                               "no implementation exists to shape them")) as ph:
            spec = ph.call(AgentCall(
                output_type=CriterionOutput,
                prompt=(correction if attempt > 1 else "") + f"Ticket `{ticket_path}`:\n\n{ticket}\n\n"
                       f"---\nWrite the criterion to `{script}`.",
                gates=[gates.artifacts_exist, gates.files_non_empty]))
            ph.log(covers=len(spec.covers), uncovered=len(spec.uncovered) or "none",
                   grounded_in=", ".join(spec.grounded_in) or "NOTHING REAL — only what it imagined",
                   command=" ".join(spec.command))

        with run.phase(PhaseParams(name=f"red_{attempt}", kind="code", owner="gate",
                                   description="Prove the criterion FAILS before any code — one "
                                               "that already passes is not describing the work")) as ph:
            first = criterion.run_criterion(run, spec.command, name="red")
            weak = criterion.is_weak(first)
            ph.log(exit=first.returncode, seconds=f"{first.duration_seconds:.1f}",
                   verdict="WEAK GATE — it already passed" if weak else "red, as expected")
            # The contract asks for under 60s. A prompt is a promise; this is a
            # measurement. A slow criterion is almost never slow out of rigour —
            # it is slow because it is fabricating a whole world instead of
            # exercising the behaviour, and that is how the 900-line scripts were
            # born.
            if first.duration_seconds > criterion.LIMIT_SECONDS:
                ph.log(**{"⚠": f"the criterion took {first.duration_seconds:.0f}s (contract: "
                               f"{criterion.LIMIT_SECONDS}s) — a sign the ticket is too big, "
                               f"or that it builds a scenario instead of exercising one"})
            if not weak:
                break
            if attempt == MAX_WEAK_GATE_ATTEMPTS:
                return run.finish(accepted=False,
                                  reason="the criterion passed before any implementation existed, "
                                         "twice — it does not discriminate what the ticket asked for")
            correction = criterion.weak_gate_correction(first, ticket) + "\n\n---\n"

    # ── build, then the same criterion again, expecting the opposite ─────────
    with run.phase(PhaseParams(name="build", kind="agent", owner="builder",
                               description="Implement until the criterion that just failed passes")) as ph:
        built = ph.call(AgentCall(
            output_type=BuildOutput,
            prompt=(f"Ticket `{ticket_path}`:\n\n{ticket}\n\n---\n"
                    f"The acceptance criterion already exists at `{script}` and FAILS TODAY. "
                    f"Run it with:\n"
                    f"    {' '.join(spec.command)}\n"
                    f"Implement until it passes. You may NOT edit the criterion."),
            gates=[gates.artifacts_exist]))

    report = None
    for attempt in range(1, max_fix + 1):
        with run.phase(PhaseParams(name=f"verify_{attempt}", kind="code", owner="gate",
                                   description="Run the ticket's criterion and the project's own "
                                               "checks in one pass, so every failure arrives together")) as ph:
            report = criterion.collect(
                criterion.run_criterion(run, spec.command, name="criterion"),
                *quality.run_quality(run).checks)
            ph.log(passed=report.passed,
                   failures=", ".join(c.name for c in report.checks if not c.passed) or "none")

        if report.passed:
            break
        if attempt == max_fix:
            break

        with run.phase(PhaseParams(name=f"fix_{attempt}", kind="agent", owner="builder", retries=1,
                                   description="Repair what the checks reported, from their "
                                               "verbatim output, in the same session")) as ph:
            built = ph.call(AgentCall(
                output_type=BuildOutput,
                prompt=f"Ticket `{ticket_path}`:\n\n{ticket}",
                previous=criterion.as_envelope(report, "verify"),
                gates=[gates.artifacts_exist]))

    # ── the reviewer: "is this what was asked for?", which the criterion cannot answer ──
    #
    # Green proves it WORKS. It does not prove it is the right thing: a green
    # suite over a feature nobody asked for is still a failed request, and
    # neither of the two covers for the other.
    #
    # It only runs if the criterion passed: reviewing code that does not even
    # work is paying an agent to confirm what `verify` already said.
    review = None
    if report and report.passed:
        for attempt in range(1, MAX_REVIEW_LOOPS + 1):
            with run.phase(PhaseParams(name=f"review_{attempt}", kind="agent", owner="reviewer",
                                       description="Rule on each thing the ticket asked for, "
                                                   "against the code on disk")) as ph:
                review = ph.call(AgentCall(
                    output_type=ReviewOutput,
                    prompt=f"Ticket `{ticket_path}`:\n\n{ticket}",
                    previous=built,
                    gates=[gates.verdict_consistent]))
                ph.log(approved=review.approved,
                       blocking=", ".join(review.blocking) or "none")

            if review.approved or attempt == MAX_REVIEW_LOOPS:
                break

            with run.phase(PhaseParams(name=f"revise_{attempt}", kind="agent", owner="builder", retries=1,
                                       description="Close the gaps the reviewer named, without "
                                                   "touching what it approved")) as ph:
                built = ph.call(AgentCall(
                    output_type=BuildOutput,
                    prompt=f"Ticket `{ticket_path}`:\n\n{ticket}",
                    previous=review,
                    gates=[gates.artifacts_exist]))

            # A revision that touched code goes back through the criterion:
            # fixing what the reviewer named is a chance to break what already
            # passed.
            with run.phase(PhaseParams(name=f"reverify_{attempt}", kind="code", owner="gate",
                                       description="Re-run the criterion — a revision that changed "
                                                   "code can break what was already green")) as ph:
                report = criterion.collect(
                    criterion.run_criterion(run, spec.command, name="criterion"),
                    *quality.run_quality(run).checks)
                ph.log(passed=report.passed)
            if not report.passed:
                break

    # ── only green AND approved lands ────────────────────────────────────────
    green = bool(report and report.passed and review and review.approved)
    if green:
        with run.phase(PhaseParams(name="commit", kind="code", owner="git",
                                   description="Land the ticket and its criterion together, so the "
                                               "guard ships with what it guards")) as ph:
            message = built.commit_message or f"{ticket_path.stem}: {built.summary}"
            # ONLY what this run's agents changed. `commit_all` would sweep the
            # whole tree, and in a repo with work in progress that takes the
            # engineer's work along with it, under the ticket's message.
            ph.log(sha=git_helper.commit_paths(message, run.touched),
                   message=message, files=len(run.touched))

    # MARK THE TICKET, even when the run was fired by hand.
    #
    # Only the frontier loop used to write `Status:`. Anyone using `/run`
    # directly built, committed, and the ticket went on saying `ready-for-agent`
    # — so the frontier, later, recomputed everything from scratch and ordered a
    # rebuild of what was already on main. It costs one paid execution per
    # already-finished ticket.
    #
    # Best-effort on purpose: a hand-written ticket may not have the line, and
    # failing to mark does not undo a commit that already happened.
    try:
        target = next((t for t in F.load(ticket_path.parent) if t.path.resolve() == ticket_path.resolve()), None)
        if target:
            F.mark(target, F.DONE if green else F.FAILED)
    except OSError:
        pass

    if green:
        reason = ""
    elif report and report.passed and review and not review.approved:
        reason = f"the reviewer refused: {'; '.join(review.blocking) or 'no detail given'}"
    else:
        reason = f"the checks kept failing after {max_fix} repair attempt(s)"
    return run.finish(accepted=green, reason=reason)


def _suffix(repo_root) -> str:
    """Match the repo's language so the criterion is runnable by its own tooling."""
    root = Path(repo_root)
    if list(root.glob("package.json")) or list(root.glob("bun.lock")):
        return ".test.ts"
    return "_test.py"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticket", type=Path, help="path to one ticket file")
    parser.add_argument("--max-fix", type=int, default=MAX_FIX_LOOPS)
    parser.add_argument("--no-checks", action="store_true", dest="allow_placeholders",
                        help="run even with placeholder checks — only this ticket's criterion holds")
    parser.add_argument("--config", default="adws/adw_mill_config/mill.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(args.ticket, args.max_fix, args.allow_placeholders, args.config, args.adw_id))
