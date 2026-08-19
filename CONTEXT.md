# CONTEXT — Mill vocabulary

The project's ubiquitous language. Use these terms exactly; avoid the listed
synonyms. Every document in this repository — `SKILL.md`, the cookbooks, the
references, the agent contracts — is written in these words.

## Core

- **factory** — this repository: the machinery. It is distinct from the
  **target project**, where the factory is installed and the real product is
  built. The factory is NOT the project — the check detector intentionally
  excludes `adws/`.
- **ADW** (*AI Developer Workflow*) — a deterministic Python flow
  (`adws/adw_*.py`) that sequences phases, controls retries, and enforces the
  criterion. *Avoid: pipeline, workflow, script.*
- **phase** — an ADW step with an explicit `kind`:
  - `agent` — requires reading and deciding
  - `code` — a known invocation; **never** becomes an agent
  - `engineer` — pauses for the human

  *Avoid: step, stage (a stage belongs to the engineer flow, not the ADW).*
- **adw_id** — the identifier that joins a feature into one trace. Pass it via
  `--adw-id` to enter an existing session rather than open another.
- **role / roster** — the entry in `adws/adw_mill_config/mill.config.yaml` that
  binds a role → model → effort → permissions. Changing the model is a
  one-line edit. *Avoid: agent (the agent is an execution; the role is the
  declaration).*

## The criterion

- **acceptance criterion** — the executable script that defines “done”, written
  **before** code exists by a role that **does not build**. The builder **does
  not see** the criterion. *Avoid: gate (its v1 name), validator (the role, not
  the thing), test (a test belongs to the suite).*
- **red baseline** — the requirement that the criterion **fail** in the
  repository's current state. A criterion that already passes discriminates
  nothing.
- **weak gate** — the criterion passed on the baseline even after a correction
  pass. The run stops to fix the criterion, not to build.
- **real anchor** — the requirement that the criterion open at least one sample
  of real data. A fixture invented by the agent itself is not evidence.
- **verify / check** — deterministic validation (test, lint, typecheck, build)
  run by code, detected from the project rather than memorized. The criterion
  enters verify as one more check.

## The work

- **spec** — the decided design, in seven sections, versioned in
  `.scratch/<feature>/`. The agent **drafts** what the engineer has already
  decided; it does not decide.
- **ticket** — a **vertical** slice with `Blocked by:` and `Status:` in the file
  itself. Status lives in the ticket rather than a separate database, so it
  survives a session and `frontier` does not rerun completed work. *Avoid:
  task, issue, card.*
- **frontier** — the set of tickets whose blockers are all complete. It is what
  can start now.
- **wave** — one frontier pass. **Within** a wave tickets run in parallel, each
  in its own worktree from the same commit; **between** waves integration is
  sequential. *Avoid: round, batch.*
- **worktree** — a git worktree isolated per ticket and created **outside** the
  repository. Leftovers from a prior execution are removed, never reused.
  Merging uses `--no-ff` and aborts on conflict without guessing.

## Contracts

- **envelope** — a role's typed output (a subclass of `EnvelopeBase`). Its
  contract is a **synchronized triad**: Pydantic type in `data_types.py`, JSON
  example in the role's `user.md`, and `output_type=` at the call site. Changing
  one without the other two breaks at runtime, not in a test.
- **`writes:`** — the **boundary**: paths a role may touch. Naming a path
  unlocks a protected file.
- **`tools:`** — the **capability**: what it can do. Both are necessary, and
  neither is sufficient alone.
- **`protected_files`** — files no role touches without explicit permission.
  It includes `tests/acceptance/`, which prevents a builder from editing the
  proof.

## Observability

- **evidence** — what remains on disk:
  `adws/adw_data/sessions/<adw_id>/`. **Agent state is never evidence; only the
  disk is.**
- **raw_output.jsonl** — every agent-stream event, written incrementally. It is
  what the pi viewer reads by byte offset.
- **notional cost (`estimated_cost`)** — a subscription plan returns
  `cost.total = 0`. Cost is **estimated** from tokens and marked as an estimate.
  **It is never an invoice.** *Avoid: cost (without the qualifier).*

## Entry points

- **skill** (this repository's root: `SKILL.md`, `cookbooks/`, `references/`) —
  teaches any harness to install and operate the factory. It carries
  **operation, never judgment**: the phase graph lives in Python, not Markdown.
  `pi/skills/mill/SKILL.md` is the pi-side equivalent.
- **viewer** (`pi/extensions/mill.ts`) — the pi extension. It is a **viewer,
  never an orchestrator**: it reads what the factory wrote to disk and renders
  it with pi's own renderers. Closing pi does not kill a run.
- **`just`** — the seven stages in the order they are used. The justfile is
  editable; it belongs to the target project, not the factory.

## Engineer flow

- **stage** — one of the seven steps invoked by the engineer: `research`,
  `investigate`, `spec`, `tickets`, `run`, `frontier`, `review`. It is
  distinct from a **phase**, which is internal to an ADW. Seven stages ride on
  six ADW files: `research` and `investigate` are the same script, split by
  `--question`.
- **fan-out (research fusion)** — two isolated minds study the same repository
  and idea **without speaking to each other**, then an architect decides. The
  value is in the **divergence**: if they talked, they would converge.
- **HITL at the endpoints, AFK in the middle** — the engineer decides the design
  and approves the result; between those points the factory proceeds alone.
- **real proof** — running against the real world (real git, a live agent,
  project data). Every real proof in this repository has found a defect.
