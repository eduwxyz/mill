#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Spec — turn a decided design into the document that says what and why.

Usage:
    uv run adws/adw_spec.py "<the engineer's answers, or a path to them>" [--design design.md] [--out specs/<slug>.md] [--config ...] [--adw-id a1b2c3d4]

Phases: engineer(request) -> speccer

Runs AFTER research_fusion, and normally with its `--adw-id`, so the spec and
the disagreement that produced it share one trace. The engineer's answers to
`engineer_calls` are the input: that is the only thing the architect could not
settle on its own.

It stops at the spec on purpose, and does NOT go on to tickets. The spec is the
one artifact the engineer actually has to read — everything downstream is built
on it, so a wrong spec is a wrong set of tickets discovered one ticket at a
time. Two minutes of reading here is the cheapest correction in the chain.

The gate is `has_sections`, not `artifacts_exist`: a spec with the right shape
and a hollow `## Testing Decisions` passes existence and fails the reader.
"""

import argparse
import sys
from pathlib import Path

from adw_modules import agents, gates, naming, session, utils
from adw_modules.data_types import AgentCall, PhaseParams, SpecOutput

REQUIRED_AGENTS = ["speccer"]

SECTIONS = ("Problem Statement", "Solution", "User Stories", "Implementation Decisions",
            "Testing Decisions", "Out of Scope", "Further Notes")


def main(prompt: str, design: str = "design.md", out: str | None = None, title: str | None = None,
         config: str = "adws/adw_mill_config/mill.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    # The prompt here is the engineer's ANSWERS, not the feature's name — slugging
    # it produced `specs/resposta-pergunta-do-arquiteto-sim-o-total-deve-...md`
    # on the first real run. A name nobody can scan is a spec nobody reopens, so
    # the fallback is the session id: ugly, but never misleading.
    # Everything about a feature lives together: spec, tickets and notes in the
    # SAME directory. Splitting them into `specs/` and `tickets/` scattered one
    # thing across two places, and whoever opens `.scratch/<feature>/` sees the
    # whole line of reasoning.
    #
    # Version controlled, deliberately: the spec is exactly what gets re-read
    # three months later, and a purely local `.scratch` disappears.
    if out:
        target = Path(out)
    else:
        feature = naming.slug(title) if title else f"feature-{run.adw_id}"
        target = Path(".scratch") / feature / "spec.md"

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Take the engineer's answers to what the architect "
                                           "could not settle")) as ph:
        ph.log(input=prompt, design=design, spec=str(target))

    with run.phase(PhaseParams(name="spec", kind="agent", owner="speccer",
                               description="Put the decided design in the requester's language, "
                                           "before any code exists to blur it")) as ph:
        spec = ph.call(AgentCall(
            output_type=SpecOutput,
            prompt=(f"{prompt}\n\n---\nRead `{design}` from your context handoff dir, and read "
                    f"`docs/adr/` if it exists. Write the spec to `{target}`."),
            gates=[gates.artifacts_exist, gates.files_non_empty, gates.has_sections(*SECTIONS)]))
        ph.log(spec=str(target), seams=len(spec.seams), open_questions=len(spec.open_questions))

    return run.finish(accepted=spec.status == "success",
                      reason="the speccer did not produce a spec")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--design", default="design.md", help="the architect's file, in the handoff dir")
    parser.add_argument("--out", default=None, help="exact path for the spec; wins over --title")
    parser.add_argument("--title", default=None, help="the FEATURE's name — the filename slug comes from it")
    parser.add_argument("--config", default="adws/adw_mill_config/mill.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(utils.resolve_prompt(args.prompt), args.design, args.out, args.title,
                  args.config, args.adw_id))
