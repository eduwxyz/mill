#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Tickets — cut a spec into tracer bullets with honest blocking edges.

Usage:
    uv run adws/adw_tickets.py <path/to/spec.md> [--out-dir tickets/<slug>] [--config ...] [--adw-id a1b2c3d4]

Phases: engineer(request) -> slicer

Runs after `adw_spec`, normally with its `--adw-id`, so the spec and its
breakdown share one trace.

**The approval step is yours, and it is deliberately not automated.** Matt's
skill quizzes the engineer here — granularity right? edges honest? anything to
merge or split? — and iterates until he approves. There is nobody to quiz
inside a workflow, so instead the envelope carries exactly what that quiz would
show (title, blocked_by, delivers) and the tickets sit on disk as files. You
read them before any `run` spends money on them; that reading IS the approval.

What code CAN check, it checks: `tickets_form_a_dag` proves the breakdown is
startable and finishable before you ever open one. A graph is arithmetic, and
an agent re-reading its own list to find a cycle is grading its own homework.
"""

import argparse
import sys
from pathlib import Path

from adw_modules import agents, gates, naming, session
from adw_modules.data_types import AgentCall, PhaseParams, TicketsOutput

REQUIRED_AGENTS = ["slicer"]


def main(spec_path: Path, out_dir: str | None = None,
         config: str = "adws/adw_mill_config/mill.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    # The PATH comes from the argument, the CONTENT comes from disk. Deriving the
    # path from the text's first line looked equivalent and is not:
    # `resolve_prompt` reads the file when handed a path, so the "first line"
    # became the spec's first heading and the tickets ended up in
    # `tickets/problem-statement/`.
    if not spec_path.is_file():
        print(f"spec not found: {spec_path}", file=sys.stderr)
        return 1
    spec = spec_path.read_text(encoding="utf-8")
    # Next to the spec that generated them: `.scratch/<feature>/issues/`. When the
    # spec is `.scratch/<feature>/spec.md`, the feature's directory is already its
    # parent.
    if out_dir:
        target = Path(out_dir)
    elif spec_path.name == "spec.md":
        target = spec_path.parent / "issues"
    else:
        target = Path(".scratch") / naming.slug(spec_path.stem) / "issues"

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Take the approved spec and say where its tickets land")) as ph:
        ph.log(spec=str(spec_path), tickets_dir=str(target))

    with run.phase(PhaseParams(name="tickets", kind="agent", owner="slicer",
                               description="Cut the work into slices that each stand up alone, "
                                           "so a wrong one costs one slice")) as ph:
        breakdown = ph.call(AgentCall(
            output_type=TicketsOutput,
            prompt=(f"Spec: `{spec_path}`\n\nWrite one file per ticket into `{target}/`.\n\n"
                    f"{spec}"),
            gates=[gates.artifacts_exist, gates.files_non_empty, gates.tickets_form_a_dag]))

        # The breakdown goes to the console in the shape the engineer needs to
        # judge it — the numbers alone say nothing about whether the cut is right.
        for ticket in breakdown.tickets:
            blockers = ", ".join(str(b) for b in ticket.blocked_by) or "nada"
            ph.log(**{f"#{ticket.number:02d}": f"{ticket.title}  ·  bloqueado por: {blockers}"})
        ph.log(frontier=breakdown.frontier or "(vazia)", total=len(breakdown.tickets))

    return run.finish(accepted=breakdown.status == "success",
                      reason="the slicer did not produce a breakdown")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="path to the spec file")
    parser.add_argument("--out-dir", default=None, help="where ticket files land; default tickets/<spec-slug>")
    parser.add_argument("--config", default="adws/adw_mill_config/mill.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(args.spec, args.out_dir, args.config, args.adw_id))
