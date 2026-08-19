# Install

`/mill install` — stamp the entire factory out of the skill and into the current working directory.

## Run it

```bash
uv run ~/.claude/skills/mill/scripts/install.py
```

Run from the **target repo root** — the cwd is where everything lands. If you keep the skill somewhere else, point at that checkout's `scripts/install.py` instead; the path above assumes the skill lives in your user scope.

## What gets stamped

`install.py` copies `templates/` into the cwd:

| Stamped | From | Tracked? |
|---|---|---|
| `adws/adw_mill_config/mill.config.yaml` | `templates/mill.config.yaml` | yes — the agent roster |
| `.env.sample` | `templates/env.sample` | yes |
| `adws/adw_*.py` | `templates/adws/` | yes — six files, carrying the seven stages (research_fusion serves two) |
| `adws/adw_modules/` | `templates/adws/adw_modules/` | yes — all low-level logic |
| `adws/adw_tests/` | `templates/adws/adw_tests/` | yes — the 71 factory tests |
| `adws/adw_data/prompt_engineering/{researcher,architect,speccer,slicer,gatekeeper,builder,reviewer,critic}/` | `templates/prompt_engineering/` | yes — **the user-owned home for prompts** |
| `adws/adw_data/harness_engineering/` | `templates/harness_engineering/` | yes — **the user-owned home for pi extensions** |
| `justfile` | `templates/justfile` | yes — the stages in usage order, plus the trace reads |
| `adws/adw_data/sessions/`, `adws/adw_data/mill.db` | created at runtime | no — gitignored |

The two `*_engineering` dirs mirror the two config keys of the same name: `prompt_engineering` is what an agent is told, `harness_engineering` is what its harness can do. Both are yours the moment they are stamped. Edit them in `adws/adw_data/`, never back inside the skill.

`harness_engineering/` ships with `subagents.ts` — the pi extension backing `subagent_create` / `_continue` / `_list` / `_remove`. No agent in the starter roster loads it; wire it into an agent's `harness_engineering:` list (and name its tools in that agent's `tools:` list) when you want it. See `references/config.md`.

## Idempotency

Re-running is safe. `install.py` skips **every** file that already exists — your config, your prompts, and previously stamped code alike — and reports what it skipped, so a second run doubles as a drift check. To refresh stamped code (`adw_modules/`, the stage `adw_*.py`) to the skill's current version, run with `--force` — but know that `--force` overwrites ALL existing stamped files, including `mill.config.yaml` and `prompt_engineering/`, so commit or back up user-owned edits first.

## Post-install checklist

1. **Env** — `cp .env.sample .env`. The starter roster needs **no API key**: every agent runs on `openai-codex/*` and `claude-bridge/*`, which pi reaches through the plan logins you already have in the terminal. If you re-point an agent at a keyed provider (`openrouter/...`, `google/...`), that provider's key goes in `.env`.
2. **Pi is installed and on PATH** — `pi --version`. Set `PI_PATH` in `.env` if it is not.
3. **The models resolve** — `pi --list-models` must show `openai-codex` and `claude-bridge` among the providers, and the ids the config names. See `references/config.md` for how model resolution works and why a bare id is rejected.
4. **Gitignore** — `install.py` appends `adws/adw_data/sessions/`, `adws/adw_data/mill.db*`, and `.env` for you; confirm they landed. All three are runtime or secrets and must never be committed.
5. **Git repo, and the factory committed** — `adw_run.py` ends in a commit phase, which raises if the cwd is not a git repository. Run `git init` and make a first commit. Then commit `adws/` itself: `adw_frontier.py` builds each ticket in a worktree created from HEAD, and what is not in HEAD does not exist in there. `frontier` refuses to start until it is, and says so.
6. **Smoke test** — the cheapest end-to-end path is one sourced answer:

```bash
just investigate "which test runner does this repo already use?"
```

Green means the whole path works: config validated, session minted, Pi ran, envelope parsed, events landed in `adws/adw_data/mill.db`. Verify the trace exists before trusting anything larger:

```bash
just sessions
# or, raw:
sqlite3 adws/adw_data/mill.db "select adw_id, status from sessions order by started_at desc limit 1;"
```

If the smoke test fails, fix it before running a stage that writes code — every multi-agent ADW rides this exact path.

## The three entry points that are not stamped

`install.py` stamps the runtime into the project. Three pieces stay in the skill checkout and are wired up once, per machine:

- **The skill you are reading** — put the checkout at `~/.claude/skills/mill/` (clone or symlink) and any Claude-Code-compatible harness picks it up. `pi/skills/mill/SKILL.md` is the pi-side equivalent.
- **The pi extension** — `pi/extensions/mill.ts` registers `/research`, `/investigate`, `/spec`, `/tickets`, `/run`, `/frontier`, `/stop` and the `mill` tool. Load it with `pi -e <path-to>/pi/extensions/mill.ts`, or add it to your pi config. Without it everything still works through `just`; you simply do not get the live panel.
- **The visualizer** — `apps/visualizer/` runs from the skill checkout and is pointed at a project's db: `MILL_DB=<repo>/adws/adw_data/mill.db bun run dev:all`. It never needs to be installed into the project.
