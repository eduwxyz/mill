#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Review — read the WHOLE feature and say what came out crooked.

Usage:
    uv run adws/adw_review.py <.scratch/<feature>> [--base <ref>] [--config ...] [--adw-id a1b2c3d4]

Phases: engineer(request) -> code(changes) -> critic

The stage that was missing, and the only one that looks at the whole.

Every ticket went through a criterion that failed first and passed afterwards,
and through a reviewer that confirmed it was what had been asked for. **None of
that looked at the whole.** A file touched by seven tickets grows in seven
directions and none of them is wrong on its own; two solutions to the same
problem come in through different doors and both pass.

Measured on the first real project: `server.ts` took SEVEN commits from distinct
tickets, and nobody at any point asked whether it still had a good shape. The
factory proved it was finished; nothing asked whether it was good.

**It fixes nothing, on purpose.** Every finding becomes a ticket, and the ticket
goes through the same red criterion as all the others — a refactor included. An
agent that fixed things here would be changing code with no gate, in the one
place in the flow where nobody is watching.

Capturing the diff is a CODE phase: `git diff` against a base is two commands,
not a judgement call. And it fails loudly when the diff is empty, before the
critic is born — there is nothing to review, and finding that out at the cost of
an agent would be waste.
"""

import argparse
import sys
from pathlib import Path

from adw_modules import agents, changes, gates, session
from adw_modules.data_types import AgentCall, ChangeCapture, PhaseParams, ShapeOutput

REQUIRED_AGENTS = ["critic"]
CONFIG = "adws/adw_mill_config/mill.config.yaml"


def main(feature_dir: Path, base: str = "main",
         config: str = CONFIG, adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    destination = feature_dir / "shape-review.md"

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Take the finished feature and the point to measure "
                                           "it against")) as ph:
        ph.log(feature=str(feature_dir), base=base, report=str(destination))

    with run.phase(PhaseParams(name="changes", kind="code", owner="git",
                               description="Capture everything the feature changed, so the critic "
                                           "reads the whole of it and not one ticket at a time")) as ph:
        # `include_untracked`: a file born inside the feature is part of it, even
        # if the ticket's commit never reached it.
        captured = changes.capture(run, ChangeCapture(base=base, max_diff_lines=6000,
                                                      include_untracked=True))
        ph.log(files=len(captured.files) + len(captured.untracked),
               lines=f"+{captured.insertions} -{captured.deletions}",
               base=captured.base.label)

    with run.phase(PhaseParams(name="review", kind="agent", owner="critic",
                               description="Name what only shows up when the whole feature is read "
                                           "at once — no ticket could see it")) as ph:
        shape = ph.call(AgentCall(
            output_type=ShapeOutput,
            prompt=(f"The feature lives in `{feature_dir}` (spec and tickets are inside).\n"
                    f"Write the report to `{destination}`."),
            previous=changes.as_envelope(captured),
            gates=[gates.artifacts_exist, gates.files_non_empty]))
        for f in shape.findings:
            ph.log(**{f"[{f.severity}]": f"{f.what[:90]}  ·  {', '.join(f.where[:2])}"})
        ph.log(findings=len(shape.findings) or "none", verdict=shape.verdict[:100])

    # A finding does NOT fail the run. The critic did its job by reporting; who
    # decides what to do with the list is the engineer. Failing here would turn
    # "this feature has debt" into "this execution failed", which are different
    # things and lead to different reactions.
    return run.finish(accepted=shape.status == "success",
                      reason="the critic produced no report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feature", type=Path, help="the .scratch/<feature> directory")
    parser.add_argument("--base", default="main",
                        help="the point to measure against; use the commit BEFORE the first ticket")
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(args.feature, args.base, args.config, args.adw_id))
