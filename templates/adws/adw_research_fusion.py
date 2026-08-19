#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Research Fusion — two isolated heads study one idea, an architect decides.

Usage:
    uv run adws/adw_research_fusion.py "<prompt or path/to/prompt.md>" [--question] [--config ...] [--adw-id a1b2c3d4]

Phases: engineer(request) -> researcher_a -> researcher_b -> architect

For the front of the work, where the idea is still vague and no test can be
written for it yet. Two research agents on DIFFERENT models answer the same
question without seeing each other, and the architect turns what they could not
both be right about into a decision — recommending a side, and naming what
stays the engineer's.

**Isolation is what makes this work; concurrency only makes it faster.**
Neither head receives the other's envelope (`previous=None` on both), so `b`
cannot converge onto `a` — that holds whether they run together or apart.

They now run TOGETHER, which cuts the phase to the slower head instead of the
sum of both. What blocked it was never the design: it was the tracer refusing a
SQLite connection from a second thread. See `tracer._Locked`.

The architect reads the two files off DISK rather than trusting the envelopes.
An agent reporting `status: success` is not evidence that it wrote anything —
the artifact gate below checks that claim, and reading the file is what catches
the rest.
"""

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor

from adw_modules import agents, gates, session, utils
from adw_modules.data_types import AgentCall, ArchitectOutput, PhaseParams, ResearchOutput

REQUIRED_AGENTS = ["researcher_a", "researcher_b", "architect"]

# Two sizes of question, and confusing them is expensive in both directions.
#
# IDEA: "I want an app that does X" — vague, shapeless, and the value is in two
# divergent readings of the whole problem.
#
# QUESTION (`--question`): "which database here?" — it comes up mid-interview, it
# has an answer, and the engineer is WAITING. Treating it as an idea would spend
# minutes and dollars to decide one line; treating an idea as a question would
# deliver a shallow answer to the thing that most needed depth.
BRIEF_IDEA = ("Study this repository, then write your approach to the file named below.\n"
              "Keep it concrete enough that a builder could start from it.")
BRIEF_QUESTION = (
    "This is a QUESTION raised mid-interview, not a feature to design. The engineer is\n"
    "waiting on it, so answer it and stop: take a position, ground it in what this\n"
    "repository actually does, and name what would change your mind. Do not design\n"
    "anything beyond what the question asks.")

FILE_A = "research_a.md"
FILE_B = "research_b.md"
FILE_DESIGN = "design.md"


def main(prompt: str, question: bool = False,
         config: str = "adws/adw_mill_config/mill.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)
    agents.validate(cfg, REQUIRED_AGENTS)
    run = session.ensure(cfg, adw_id)

    brief = BRIEF_QUESTION if question else BRIEF_IDEA
    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description=("Capture the question the interview could not settle"
                                            if question else
                                            "Capture the idea while it is still vague"))) as ph:
        ph.log(input=prompt, mode="question" if question else "idea")

    def study(label: str, owner: str, outfile: str):
        # `previous=None` is the isolation, and it is the whole design: a head
        # that saw the other's envelope would converge on it, and convergence
        # is exactly what this phase must not produce.
        with run.phase(PhaseParams(name=f"research_{label}", kind="agent", owner=owner,
                                   description="Ground the idea in this repo, alone, so the "
                                               "disagreement with the other head is real")) as ph:
            return ph.call(AgentCall(
                output_type=ResearchOutput,
                prompt=f"{prompt}\n\n---\n{brief}\nWrite it to `{outfile}` in your context handoff dir.",
                gates=[gates.artifacts_exist, gates.files_non_empty]))

    # IN PARALLEL. It used to be sequential, and the sequence was protecting
    # nothing: the isolation comes from `previous=None`, not from the order —
    # neither head ever saw the other. What was actually holding it back was the
    # tracer, which refused a connection from another thread; fixed in
    # `tracer._Locked`.
    #
    # The cost is the SCREEN: both write to the same terminal and the lines
    # interleave. In the UI nothing changes — there each agent already has its
    # own lane.
    with ThreadPoolExecutor(max_workers=2) as pool:
        heads = [pool.submit(study, "a", "researcher_a", FILE_A),
                 pool.submit(study, "b", "researcher_b", FILE_B)]
        for head in heads:
            head.result()          # propagates the exception from whichever head failed

    with run.phase(PhaseParams(name="architect", kind="agent", owner="architect",
                               description="Turn what the two heads could not both be right "
                                           "about into a decision the engineer can make")) as ph:
        design = ph.call(AgentCall(
            output_type=ArchitectOutput,
            # No `previous=`: handing it one head's envelope would weight that
            # head. It reads BOTH files off disk instead, which is also the
            # only way to catch a head that reported success and wrote nothing.
            prompt=(f"{prompt}\n\n---\nRead `{FILE_A}` and `{FILE_B}` from your context handoff "
                    f"dir. Write your design to `{FILE_DESIGN}` in the same dir."),
            gates=[gates.artifacts_exist, gates.files_non_empty]))
        ph.log(divergences=len(design.divergences), engineer_calls=len(design.engineer_calls))

    # Divergence count is NOT a success criterion: two heads genuinely agreeing
    # is a real outcome, and paying an architect to manufacture disagreement
    # would be worse than none. What is required is that the design exists.
    return run.finish(accepted=design.status == "success",
                      reason="the architect did not produce a design")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--question", action="store_true",
                        help="ONE question from the interview, not an idea: answers and stops")
    parser.add_argument("--config", default="adws/adw_mill_config/mill.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(utils.resolve_prompt(args.prompt), args.question, args.config, args.adw_id))
