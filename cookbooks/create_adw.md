# Create ADW

Compose a new ADW script — a thin, deterministic Python workflow over agents already in the config. Design the chain first, then generate or hand-write it.

## Step 1 — Design the chain

Answer four questions, in order:

1. **What agents, in what order?** Pick from the roster (`adws/adw_mill_config/mill.config.yaml`). **Only names in that file exist** — `agents.validate()` fails the run at startup on anything else. The starter roster:

| Agent | Use when | Output type | Typical gates |
|---|---|---|---|
| `researcher_a` / `researcher_b` | the idea is vague and two independent readings are worth more than one | `ResearchOutput` | `artifacts_exist`, `files_non_empty` |
| `architect` | two readings must be settled into one design | `ArchitectOutput` | `artifacts_exist`, `files_non_empty` |
| `speccer` | a decided design must become a spec | `SpecOutput` | `artifacts_exist`, `has_sections` |
| `slicer` | a spec must become vertical tickets with a blocking graph | `TicketsOutput` | `tickets_form_a_dag` |
| `gatekeeper` | "done" must become executable BEFORE anything is built | `CriterionOutput` | `artifacts_exist`, `files_non_empty` |
| `builder` | code must change | `BuildOutput` | `artifacts_exist`, `diff_matches_claims` |
| `reviewer` | the change must be confirmed to BE what was asked for | `ReviewOutput` | `verdict_consistent` |
| `critic` | a whole finished feature must be read at once | `ShapeOutput` | `artifacts_exist`, `files_non_empty` |
| *(no tester)* | verifying that it RUNS is a `kind="code"` phase over `quality.py`, not an agent | `QualityResult` → `as_envelope` | the exit code is the check |
| any agent, generic ask | one-off prompt, no special shape | `GenericOutput` | as needed |

`PlanOutput`, `ScoutOutput` and `DocumentOutput` also exist in `data_types.py`. They are unused by the shipped stages and kept for chains you write yourself — using one means adding the matching agent to the roster first.

   A new kind of agent needs a config entry + prompt pair + output type first — see `update_config.md`.

   **The suite and the reviewer answer different questions.** "Does it run" is a test, and code can ask that. "Is this the thing that was asked for" is a review, and only an agent can. A green suite over a feature nobody requested is still a failed request, and neither one covers for the other.

2. **Where does code act?** Git branch/commit, migrations, deploys each get their own `kind="code"` phase — never buried inside an agent phase.

   **Running the suite is one of these — there is no tester agent.** The command is written down in `quality.py`, so a `kind="code"` phase runs it (`quality.run_tests(run)` → `quality.as_envelope(result, "tests")` back into the builder) and the bounded repair loop is unchanged. An agent rediscovering `bun test` on every run buys nothing a subprocess does not already know. Capturing what changed is one of these: `changes.capture(run, ChangeCapture(base="main"))` diffs the working tree against a resolved base, writes `context_handoff/changes.diff`, and `changes.as_envelope(...)` hands it to the next agent. A diff is two git commands, not a judgement call.

3. **Does anything loop?** Test-fix cycles are bounded fix loops (see `update_adw.md`), not phase retries.

4. **What does each call need to prove?** Pick gates per call from `gates.py`: `artifacts_exist`, `files_non_empty`, `json_parses`, `diff_matches_claims`, `tests_pass("cmd")` — or an inline one-off.

## Step 2 — Ownership rules (the swim lanes depend on these)

- `kind="agent"` → `owner` MUST be an agent name from the config — it selects the harness (model, thinking, tools, prompts) AND the lane. `ph.call()` runs whoever owns the phase.
- `kind="engineer"` → `owner=run.engineer`. Every ADW opens with the engineer request phase — it is the system input record.
- `kind="code"` → `owner` is a short actor label (`"git"`, `"db"`); all code phases share the code lane.
- Phase `name` must be unique within the run (`plan`, `build`, `test_1`, `fix_1`, …) — the UI keys blocks on it.
- **`description` is required and must earn its place.** The name identifies the phase; the description explains it — what this phase does and why, in one sentence. It rides the `phase_start` event and is the only line of intent the trace, the console, and the phase block ever show. `PhaseParams` raises at construction on a blank description *or* one that merely restates the name (`commit_plan: "Commit the plan"`), so the rule fails before the phase opens rather than leaving an unreadable run in the db. Write `"Put the spec on record before any code exists to blur it"` instead.
- `retries=N` on an **agent** phase = extra gate-correction rounds re-sent into the same session (pi's `--session-id` creates-or-continues, so context stays intact). Code-phase re-execution is not implemented in v1.

## Step 3 — Generate or write it

```bash
uv run ~/.claude/skills/mill/scripts/make_adw.py --name spec_build --agents speccer,builder
```

Writes `adws/adw_spec_build.py`: one agent phase per name, chained by `previous=`, starter agents mapped to their output types, unknown agents to `GenericOutput`. It does NOT create config entries or prompt files — do that first (`update_config.md`), or `agents.validate()` will stop the run and tell you what's missing.

## The canonical skeleton

Every `adw_*.py`, generated or hand-written, is a `uv` single-file script with this shape:

```python
#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Plan Build — plan the request, then implement the plan."""

import argparse
import sys

from adw_modules import agents, gates, git_helper, session, utils
from adw_modules.data_types import AgentCall, BuildOutput, PhaseParams, SpecOutput

REQUIRED_AGENTS = ["speccer", "builder"]        # names, never models


def main(prompt: str, config: str = "adws/adw_mill_config/mill.config.yaml", adw_id: str | None = None) -> int:
    cfg = agents.load_config(config)            # 1. point to config
    agents.validate(cfg, REQUIRED_AGENTS)       # 2. fail fast — nothing spawns on a half-valid config
    run = session.ensure(cfg, adw_id)           # 3. pin-or-create the session → the Run object

    with run.phase(PhaseParams(name="request", kind="engineer", owner=run.engineer,
                               description="Capture the incoming ask")) as ph:
        ph.log(input=prompt)

    with run.phase(PhaseParams(name="spec", kind="agent", owner="speccer",
                               description="Turn the request into an implementable spec")) as ph:
        spec = ph.call(AgentCall(output_type=SpecOutput, prompt=prompt,
                                 gates=[gates.artifacts_exist, gates.files_non_empty]))

    with run.phase(PhaseParams(name="build", kind="agent", owner="builder", retries=1,
                               description="Implement the spec exactly")) as ph:
        build = ph.call(AgentCall(output_type=BuildOutput, prompt=prompt, previous=spec,
                                  gates=[gates.diff_matches_claims]))

    with run.phase(PhaseParams(name="commit", kind="code", owner="git",
                               description="Commit the working tree")) as ph:
        message = build.commit_message or f"mill({run.adw_id}): {build.summary}"
        ph.log(sha=git_helper.commit_all(message), message=message)

    return run.finish()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="inline text or a path to a prompt file")
    parser.add_argument("--config", default="adws/adw_mill_config/mill.config.yaml")
    parser.add_argument("--adw-id", default=None, help="join or pin an existing session")
    args = parser.parse_args()
    sys.exit(main(utils.resolve_prompt(args.prompt), args.config, args.adw_id))
```

## Non-negotiables

- **`REQUIRED_AGENTS` + `agents.validate()`** — declare every agent name the script uses and validate before the first phase.
- **Every agent call declares a concrete output type** from `data_types.py`. No untyped handoffs.
- **`previous=` carries the chain** — the upstream envelope lands in the next agent's `user.md` as `{{previous_envelope}}`; bulky context moves through `context_handoff/` files the envelope references.
- **The engineer request phase comes first**, always.
- **Four-param rule** — `run.phase()` and `ph.call()` each take exactly one object; new helpers with >4 params get a data type.
- **Stay thin** — sequencing and acceptance only; real logic goes in `adw_modules/` (`update_modules.md`).
- **Committing is a code phase, and it needs a fallback.** `PlanOutput`, `BuildOutput`, and `DocumentOutput` each carry a `commit_message` the agent writes **for its own work product** — the spec, the code, the write-up. It defaults to empty, so always `envelope.commit_message or <fallback>`, and commit each product with the message of the agent that made it — a chain that commits more than once must never cross them. `git_helper.commit_paths(message, run.touched)` commits only what this run's agents changed and returns the short sha; `commit_all(message)` stages the whole tree, which also sweeps in the engineer's work in progress. Both raise a clear error when the cwd isn't a git repo or nothing changed, and that raise fails the phase.

## Before you ship it

1. `uv run adws/adw_<name>.py "a tiny real request"` — watch it go green end to end.
2. Check the trace: `sqlite3 adws/adw_data/mill.db "select seq,name,kind,owner,status from phases where adw_id='<id>' order by seq;"`
3. Read the final `envelope.json` — is the output type earning its fields, or should it be sharper?
