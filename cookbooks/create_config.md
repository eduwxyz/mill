# Create Config

Generate `mill.config.yaml` — the agent roster for a target repo.

## Generate it

```bash
uv run .claude/skills/mill/scripts/make_config.py
```

Writes `adws/adw_mill_config/mill.config.yaml` — creating the directory if needed — by copying the skill's `templates/mill.config.yaml`: the starter roster (researcher_a, researcher_b, architect, speccer, slicer, gatekeeper, builder, reviewer, critic) wired to the prompt files `/mill install` stamped into `adws/adw_data/prompt_engineering/`. That path is the default every ADW and the justfile look for; `--config` overrides it. `make_config.py` refuses to overwrite an existing config unless you pass `--force`, so retuning an existing roster is a hand edit — see `update_config.md`.

## The rule

**One agent, one prompt, one purpose.** An entry defines who an agent *is*: its coding agent, model, thinking level, and exactly one system prompt plus one user prompt. How it gets *used* — the output type, a per-call user prompt override — lives at the ADW call site, never here.

## Schema

```yaml
defaults:
  coding_agent: pi                 # v1: pi only (claude_code is specced, stubbed until v2)
  model: openai-codex/gpt-5.6-luna # ALWAYS provider/model-id — a bare id is ambiguous
  thinking: medium                 # off | minimal | low | medium | high | xhigh | max
  harness_engineering: []          # pi extension names
  data_dir: adws/adw_data          # runtime home: {data_dir}/sessions/{adw_id}/{agent_name}/

observability:
  db: adws/adw_data/mill.db        # tracer writes here; the UI polls it
  poll_ms: 500                     # visualizer live-poll cadence

agents:
  - name: speccer                  # ADW scripts name agents, never models
    coding_agent: pi
    model: openai-codex/gpt-5.6-terra
    thinking: high
    color: "#34d399"               # optional hex — this agent's lane color in the visualizer
    purpose: Synthesize a decided design into a spec; never interview, never decide.
    prompt_engineering:
      system: adws/adw_data/prompt_engineering/speccer/system.md
      user: adws/adw_data/prompt_engineering/speccer/user.md

  - name: architect
    thinking: xhigh                # unset keys fall through to defaults
    purpose: Read both research files, propose the design, and name what only the engineer can answer.
    prompt_engineering:
      system: adws/adw_data/prompt_engineering/architect/system.md
      user: adws/adw_data/prompt_engineering/architect/user.md
    tools:                         # optional allowlist — omit the key entirely for all tools
      - read
      - bash
```

Every agent entry merges over `defaults`, so an entry only states what differs. Pi's builtin tools are `read`, `bash`, `edit`, `write` — a read-only recon agent gets `[read, bash]`; a builder omits `tools` altogether.

## After generating

1. Each agent needs its prompt pair to exist on disk: `adws/adw_data/prompt_engineering/{name}/system.md` and `user.md`. `agents.validate()` fails the run at startup if either is missing.
2. Write `purpose` as one sentence and make the system prompt say the same thing — the two should not drift.
3. Validate by running the smallest ADW that names your agents; a bad entry fails fast, before anything spawns.

Full field-by-field spec, thinking-level mapping, and model resolution: `references/config.md`. Retuning an existing roster: `update_config.md`.
