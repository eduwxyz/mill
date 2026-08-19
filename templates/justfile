# The seven stages, in the order you use them. Editable — this one is yours.

set dotenv-load
set positional-arguments

# `MILL_CONFIG=other.yaml just run ...` swaps the whole roster for one execution.
config := env_var_or_default("MILL_CONFIG", "adws/adw_mill_config/mill.config.yaml")
db     := "adws/adw_data/mill.db"

default:
    @just --list

# ── the front: from a vague idea to a ticket ────────────────────────────────

# two isolated minds + an architect who decides: just research "<idea>"
research *ARGS:
    uv run adws/adw_research_fusion.py --config {{config}} "$@"

# ONE question from the interview, answered with sources: just investigate "which database?"
investigate *ARGS:
    uv run adws/adw_research_fusion.py --config {{config}} --question "$@"

# the decided design in 7 sections: just spec "<your answers>" --title <feature>
spec *ARGS:
    uv run adws/adw_spec.py --config {{config}} "$@"

# vertical slices with a blocking graph: just tickets .scratch/<feature>/spec.md
tickets *ARGS:
    uv run adws/adw_tickets.py --config {{config}} "$@"

# ── the build ───────────────────────────────────────────────────────────────

# ONE ticket, behind a criterion that had to fail first: just run <ticket.md>
run *ARGS:
    uv run adws/adw_run.py --config {{config}} "$@"

# AFK: works the frontier until it empties. Always run with --dry first.
frontier *ARGS:
    uv run adws/adw_frontier.py --config {{config}} "$@"

# ── afterwards ──────────────────────────────────────────────────────────────

# reads the WHOLE feature and says what came out crooked: just review .scratch/<f> --base <ref>
review *ARGS:
    uv run adws/adw_review.py --config {{config}} "$@"

# the factory's own suite
test:
    python3 -m unittest discover -s adws/adw_tests -t adws

# ── looking ─────────────────────────────────────────────────────────────────
# The database is WAL: reading never blocks whoever is writing.

# the last 10 runs
sessions:
    @sqlite3 {{db}} "select adw_id, adw_name, status, round(total_cost,4) from sessions order by started_at desc limit 10;"

# the phases of one run: just phases <adw_id>
phases ADW_ID:
    @sqlite3 {{db}} "select seq, name, kind, owner, status from phases where adw_id='{{ADW_ID}}' order by seq;"

# what is alive right now, with pid: just procs <adw_id>
procs ADW_ID:
    @sqlite3 {{db}} "select kind, name, pid, command from processes where adw_id='{{ADW_ID}}' and ended_at is null;"
