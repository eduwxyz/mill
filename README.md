# Mill

> A software factory: **code drives the pipeline, agents do the cognitive work,
> and the engineer appears at the endpoints** — at intake and review. The system
> proceeds by itself in the middle.

Mill runs from [pi](https://github.com/earendil-works/pi) or from the command
line. It takes an idea expressed in plain English and carries it to a reviewed
commit — through an **acceptance criterion written before code exists**, so green
means *“it did what was requested”* rather than merely *“nothing broke.”*

---

## Why this exists

Anyone can make an agent write code once. Almost nobody can get the same result
twice.

When you give the entire cycle to a single agent, everything that makes the
outcome auditable disappears:

- **No boundary between stages** — you do not know which step failed.
- **No nameable acceptance criterion** — “done” becomes “the agent stopped
  talking.”
- **A new attempt discards everything it learned** — it starts from zero.
- **The only trace is a transcript** that you must read like a novel.

Mill begins with a deliberate decision: **code owns sequencing, retries, and the
acceptance criterion. The agent owns only the work inside a bounded phase.**
Everything else follows from that line.

### The lesson that kept repeating

While Mill was being built, the same defect appeared five times in different
harnesses:

| what happened | what the agent said |
| --- | --- |
| `claude -p` did not write the requested file | `ok: true`, text `"done."` |
| an environment hook leaked into the response | everything normal |
| Codex did not implement a line | `done` |

> **An agent saying it finished is never evidence that it did the work.** Only
> the disk tells the truth.

That is why Mill has an acceptance criterion, and why it is written **before**
the code and **out of the builder's reach**.

---

## The three actors

**Code** (deterministic, zero token cost) decides the path, creates worktrees,
runs tests, stores state, controls loops, commits, and merges. Code is cheap,
runs instantly, changes in a second, and is yours.

**Agents** do only the work that requires reading and deciding: research,
design, slicing, writing the criterion, building, and reviewing.

**You** decide the design and approve the result. Two endpoints, nothing in the
middle.

When an invocation is known, write it in code. `bun test` is not a judgement
call. An agent rediscovering your test runner burns a context window to learn
what a subprocess already knows — and charges for every run.

---

## The flow — seven stages

```
     YOU (HITL)                     THE FACTORY
 ─────────────────────────────────────────────────────────────────
  vague idea
      ├──── just research "<idea>" ────→ two isolated minds
      │                                   + an architect decides
      └──── just investigate "<question>" → ONE sourced answer
      ↓
  you make the call
      ↓
  just spec "<answers>" ───────→ the decided design, in 7 sections
      ↓
  just tickets <spec.md> ───────→ vertical slices + blocking graph
      ↓
 ┌────────────────────────── AFK ────────────────────────────────┐
 │  just run <ticket.md>   RED criterion → build → verify        │
 │                         → reviewer → commit                    │
 │                                                               │
 │  just frontier          waves: parallel within one; integrate │
 │                         between them — until complete          │
 └───────────────────────────────────────────────────────────────┘
      ↓
  just review .scratch/<feature> ──→ what remains wrong across the feature
      ↓
  YOU approve
```

| stage | who decides | output |
| --- | --- | --- |
| **research** | two minds diverge; an architect chooses | a document with explicit divergence |
| **investigate** | a researcher | an interview question answered **with sources** |
| **spec** | you answered; the agent drafts | the decided seven-section design, versioned |
| **tickets** | the slicer | vertical slices with explicit `Blocked by:` |
| **run** | code | one built and committed ticket, or red |
| **frontier** | code | the whole frontier, on its own |
| **review** | a critic | findings across the whole feature — they do not fail the run |

### Why the endpoints are yours and the middle is not

Sharpening an idea is where different minds find different things, and where the
choice depends on business, taste, and priority. That is yours.

Building a ticket with an existing acceptance criterion is not. That is where the
factory proceeds alone, and why `frontier` exists.

---

## The criterion must FAIL at the beginning

This is the central piece and the reason the rest exists.

Before any code, an agent **that will not build** writes an executable script
that defines “done.” Mill runs it **against the repository's current state**. If
it passes there, one of two things is true: either the criterion is too vague to
discriminate anything, or the work was already done.

In either case, final green would prove nothing — the run stops to correct the
criterion, not to build.

The builder **does not see** the criterion. Its author **does not build**.

That is the difference between *“the suite did not break”* and *“the requested
thing exists.”*

> **It must also be anchored in reality.** The criterion must open at least one
> sample of real data. The measurement that produced this rule: an importer
> passed every test against fixtures invented by the agent itself, yet read **0
> of 171** real files. *“The behaviour did not exist and now does”* is not the
> same as *“it works with real data.”*

---

## Waves

```bash
just frontier --dry        # always first: show waves without changing anything
just frontier
```

`frontier` reads tickets, builds the `Blocked by:` graph, and works in waves:

- **Within one wave** — tickets whose blockers are complete run **in parallel**,
  each in its own worktree, all from the same commit.
- **Between waves** — integration is **sequential**, one merge at a time,
  aborting on the first conflict rather than guessing.

Status lives in the ticket file itself (`**Status:**`), not in a separate
database. Completed work does not return, and state survives the session.

*A deliberate discipline:* a ticket that **fails** is not retried on its own.
Code does not insist on what broke.

---

## From pi

```
/research  /investigate  /spec  /tickets  /run  /frontier  /stop
```

The extension is a **viewer**, never an orchestrator: it reads the
`raw_output.jsonl` that the factory writes to disk and renders it with pi's own
renderers — the same `Read`, `Bash`, and `Edit` boxes you already know.

That means closing pi does not kill any run, and what you see is exactly what
happened, not an agent summary.

---

## Installation

### Prerequisites

- [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11
- [just](https://github.com/casey/just)
- [pi](https://github.com/earendil-works/pi) — the coding agent the roster runs on
- A logged-in plan for the providers the roster names (`openai-codex`,
  `claude-bridge`). **No API key is required** for the starter roster; check with
  `pi --list-models`.
- [bun](https://bun.sh) — only for the optional visualizer

### 1. Put the skill where your harness finds it

This repository *is* the skill. Clone or symlink it once, per machine:

```bash
git clone <this-repo> ~/.claude/skills/mill
# or, if it already lives somewhere else:
ln -s ~/dev/mill-new ~/.claude/skills/mill
```

Claude Code and any compatible harness now pick up `SKILL.md`, which teaches it
to install, run, and observe the factory. For pi, the equivalent is
`pi/skills/mill/SKILL.md`, and the commands come from the extension:

```bash
pi -e ~/.claude/skills/mill/pi/extensions/mill.ts
```

### 2. Install the factory into a project

```bash
cd ~/dev/your-project
uv run ~/.claude/skills/mill/scripts/install.py

cp .env.sample .env        # read it — the starter roster needs no key
just --list
```

Or, from a harness: *“install Mill here”* — the skill teaches the rest.

The agent roster lands in `adws/adw_mill_config/mill.config.yaml` — model and
effort per role. Changing a model is a one-line edit.

> **The factory must be committed.** `frontier` creates worktrees from HEAD; what
> is not in HEAD does not exist there. This once cost an entire run that died
> with *“system prompt not found”*, and a precondition now refuses to start
> before it happens.

### 3. Smoke test

```bash
just investigate "which test runner does this repo already use?"
just sessions
```

### The optional visualizer

```bash
cd ~/.claude/skills/mill/apps/visualizer
bun install
MILL_DB=~/dev/your-project/adws/adw_data/mill.db bun run dev:all
```

It is read-only and polls the same SQLite database `just sessions` reads. The db
is WAL, so looking never blocks a run.

---

## Structure

```
SKILL.md                    teaches any harness to install and operate the factory
CONTEXT.md                  the vocabulary every other document is written in
cookbooks/                  one per request — lazy-loaded by SKILL.md
references/                 the specs: config, envelope handoff, observability
templates/                  everything install.py stamps into a project
  adws/
    adw_research_fusion.py  two isolated researchers + an architect
    adw_spec.py             the decided design, in seven sections
    adw_tickets.py          vertical slices with a blocking graph
    adw_run.py              one ticket, behind a red criterion
    adw_frontier.py         the waves, AFK
    adw_review.py           the whole feature, read at once
    adw_modules/            worktree, criterion, frontier, quality, permissions, git…
    adw_tests/              71 factory tests
  prompt_engineering/       the agent contracts (system + user)
  harness_engineering/      pi extensions the roster can load
  mill.config.yaml          the roster: role → model → effort → permissions
  justfile                  the stages, in usage order
scripts/
  install.py                stamps the factory into a project
  make_adw.py               scaffolds a new ADW from the roster
  make_config.py            writes the roster into a project
pi/
  skills/mill/SKILL.md      the pi-side control bridge
  extensions/mill.ts        commands and the live viewer
apps/visualizer/            optional read-only trace UI
```

---

## Test

```bash
cd templates
python3 -m unittest discover -s adws/adw_tests -t adws
```

71 tests, no network, no agent spawned.

---

## What Mill does **not** do

Being candid about this matters more than a feature list:

- **It does not resolve merge conflicts.** It aborts and returns them to you.
- **It does not repeat a failed ticket** unless you ask.
- **It does not decide what to dispatch on its own.** The graph is always code.
- **It does not write the spec for you.** It drafts what you decided; questions
  only you can answer remain yours.
- **It does not replace human review.** `review` finds; approval is yours.

---

## Status

Personal project, under active construction. 71 factory tests.

**What has been proven end to end:** one product built from scratch with the
entire flow — research, spec, tickets, six tickets through `run` and `frontier`,
then `review`.

The factory has also proven itself twice against itself: the reviewer rejected
six times — one caught a `?? 0` that converted a corrupt field into a silent zero
in a consumption dashboard with every test green — and the critic found the
importer that read 0 of 171 real files.

**What has not yet:** large repositories, and waves with more than three tickets
in parallel.

---

## Credit

The idea of an **ADW** — an AI Developer Workflow, where deterministic code
sequences bounded agent phases instead of one agent owning the whole cycle —
comes from [IndyDevDan](https://www.youtube.com/@indydevdan). Every stage,
module, contract, and gate in this repository is an original implementation.

## License

MIT. See [LICENSE](LICENSE).
