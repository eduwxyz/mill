#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""ADW Frontier — works the frontier until it empties, or until something fails.

Usage:
    uv run adws/adw_frontier.py <.scratch/<feature>/issues> [--max N] [--parallel N] [--dry] [--config ...]

This is the OUTER loop: it talks to no agent at all. It computes which tickets
can start (all blockers complete), fires `adw_run` at each one, and recomputes.
The entire cognitive workload still happens down inside those runs.

It is the piece that closes "AFK in the middle, HITL at the endpoints": the last
human gate becomes approving the split into tickets, rather than dispatching the
twelve of them one by one.

IT STOPS ON THE FIRST FAILURE, by the engineer's decision. The alternative —
skipping what failed and carrying on with whatever is still unblocked — sounds
more productive and is worse: a ticket that fails almost always means the spec
or the split was wrong, and carrying on builds more things on top of the same
defect, more expensive to undo later. Failure is signal, and signal wants
attention.

IT PARALLELIZES WITHIN A WAVE AND INTEGRATES BETWEEN WAVES. Every ticket
unblocked at that moment starts from the SAME commit, each in its own worktree,
and they only meet at integration — which is sequential, in ticket order. That
way none of them builds on top of code that does not exist yet, and a conflict
shows up at the merge, where there is a human, instead of inside an agent.

NOBODY RESOLVES A CONFLICT HERE. The merge is aborted whole, the branch and the
checkout stay standing, and the loop stops. An agent resolving a conflict on its
own is the most expensive way to lose code: the damage hides inside a merge
nobody read.

`--parallel 1` returns to the old behaviour: one at a time, in the main tree,
with no isolation.
"""

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from adw_modules import frontier as F
from adw_modules.utils import new_id
from adw_modules import git_helper
from adw_modules import worktree as W

DEFAULT_MAX = 50          # backstop against a runaway loop, not a target
DEFAULT_PARALLEL = 3      # ceiling on simultaneous tickets; each one is a paid agent
CONFIG = "adws/adw_mill_config/mill.config.yaml"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().removesuffix(".md")).strip("-")[:40] or "ticket"


def _run_ticket(ticket: F.Ticket, config: str, extra: list[str], cwd: Path | None = None,
                env: dict[str, str] | None = None, adw_id: str | None = None,
                script: Path | None = None) -> int:
    # EVERYTHING ABSOLUTE: the script AND the ticket.
    #
    # The worktree is a checkout of HEAD, and in a project where `adws/` has not
    # been committed yet THE FACTORY DOES NOT EXIST inside it — `uv run
    # adws/adw_run.py` died with "No such file or directory" before any phase.
    # The same goes for the ticket, which usually lives in `.scratch/` without a
    # commit.
    #
    # Both are TOOL and INPUT, not the ticket's code: they come from the main
    # repository. What the checkout has to contain is only what the ticket will
    # change.
    argv = ["uv", "run", str((script or Path("adws/adw_run.py")).resolve()),
            str(ticket.path.resolve()), "--config", config, *extra]
    if adw_id:
        argv += ["--adw-id", adw_id]
    print(f"\n\033[1m▶ #{ticket.number:02d}\033[0m {ticket.path.name}")
    return subprocess.run(argv, cwd=cwd, env=env).returncode


def _isolated_wave(wave: list[F.Ticket], repo: Path, branch: str, config: str,
                   extra: list[str], parallel: int) -> dict[int, str]:
    """Runs the whole wave in worktrees, integrates what came back green, returns the state.

    The tickets ALL start from the same commit and only meet at integration.
    That is what makes the parallelism safe: none of them sees another's
    half-way state, and the conflict — when there is one — shows up at the
    merge, where there is a human, instead of inside an agent.
    """
    base = git_helper.rev("HEAD")
    trees = {t.number: W.create(repo, t.number, _slug(t.path.name), base) for t in wave}
    state: dict[int, str] = {}

    # THE TRACE STAYS IN THE MAIN REPO. `db` and `data_dir` are relative to the
    # cwd, and each child's cwd is its worktree — which is deleted the moment the
    # ticket integrates. Without this, the commit survives and the evidence of
    # how it was made is deleted along with the checkout, which is exactly the
    # opposite of what this system promises.
    environment = {
        **os.environ,
        "MILL_DB": str(repo / "adws/adw_data/mill.db"),
        "MILL_DATA_DIR": str(repo / "adws/adw_data"),
    }

    # THE ID IS GENERATED HERE, not by the child.
    #
    # With three runs in parallel writing to the same stdout, the `adw_id:` each
    # one prints arrives interleaved and nobody knows whose it is. Generating it
    # up front, the loop publishes the ticket↔session pair on a line the
    # extension reads to build one column per ticket — and the trace stays
    # navigable even with no screen at all.
    ids = {t.number: new_id(8) for t in wave}
    for t in wave:
        print(f"[mill] ticket={t.number:02d} adw={ids[t.number]} file={t.path.name}",
              flush=True)

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        script = repo / "adws" / "adw_run.py"
        futures = {t.number: pool.submit(_run_ticket, t, config, extra,
                                         trees[t.number].path, environment, ids[t.number], script)
                   for t in wave}
        codes = {n: f.result() for n, f in futures.items()}

    # INTEGRATION IS SEQUENTIAL and in ticket order. Parallel would be faster and
    # would have the very race the worktrees exist to eliminate.
    for ticket in wave:
        wt = trees[ticket.number]
        if codes[ticket.number] != 0:
            state[ticket.number] = F.FAILED
            print(f"\033[31m  ✗ #{ticket.number:02d} failed — the tree "
                  f"{wt.path} is left for you to look at\033[0m", file=sys.stderr)
            continue                      # failed: no merge, and the checkout STAYS
        if not W.has_commits(repo, wt, base):
            state[ticket.number] = F.DONE
            print(f"\033[33m  ⚠ #{ticket.number:02d} passed without committing anything\033[0m")
            W.remove(repo, wt)
            continue
        ok, detail = W.merge(repo, wt, branch)
        if ok:
            state[ticket.number] = F.DONE
            print(f"\033[32m  ✓ #{ticket.number:02d} integrated\033[0m {detail}")
            W.remove(repo, wt)
        else:
            # A conflict is NOT resolved here, nor by an agent. The branch and the
            # checkout stay standing so you can resolve it with the history in hand.
            state[ticket.number] = F.FAILED
            print(f"\033[31m  ✗ #{ticket.number:02d} DID NOT integrate: {detail}\033[0m\n"
                  f"    branch: {wt.branch}\n    tree: {wt.path}", file=sys.stderr)
    return state


def main(issues_dir: Path, limit: int = DEFAULT_MAX, dry: bool = False,
         parallel: int = DEFAULT_PARALLEL,
         config: str = CONFIG, extra: list[str] | None = None) -> int:
    # `--dry` simulates IN MEMORY. Marking the file to "advance the simulation"
    # left the tickets as `done` — the engineer previewed the order and, on the
    # real run, found everything complete with nothing built. A forecast that
    # changes the world is not a forecast.
    simulated: set[int] = set()
    if not issues_dir.is_dir():
        print(f"ticket directory not found: {issues_dir}", file=sys.stderr)
        return 1

    done_now = 0
    while done_now < limit:
        tickets = F.load(issues_dir)
        for t in tickets:
            if t.number in simulated:
                t.status = F.DONE
        if not tickets:
            print(f"no tickets in {issues_dir}", file=sys.stderr)
            return 1

        pending = [t for t in tickets if not t.done]
        if not pending:
            print(f"\n\033[32m✓ frontier empty — all {len(tickets)} tickets are complete\033[0m")
            return 0

        ready = F.frontier(tickets)
        if not ready:
            # Not everything is complete and nothing is released: either something
            # failed, or the graph deadlocks. Both need the engineer, and saying
            # WHICH is the difference between a useful warning and an "I don't
            # know what happened".
            stuck = [t for t in tickets if t.status.lower() == F.FAILED]
            reason = (f"#{stuck[0].number:02d} failed and {len(pending) - len(stuck)} "
                      f"tickets depend on it" if stuck else
                      "the pending ones block each other — the graph does not close")
            print(f"\n\033[31m✗ the loop stopped: {reason}\033[0m", file=sys.stderr)
            for t in pending:
                print(f"    #{t.number:02d} {t.status:16} ← {t.blocked_by or 'nothing'}", file=sys.stderr)
            return 1

        wave = ready if parallel > 1 else ready[:1]
        print(f"\n\033[1mwave:\033[0m {[t.number for t in wave]}"
              + (f"  (frontier {[t.number for t in ready]})" if len(wave) < len(ready) else ""))

        if dry:
            for t in wave:
                print(f"[dry] would run #{t.number:02d} {t.path.name}")
                simulated.add(t.number)     # memory only — the disk stays untouched
            done_now += len(wave)
            continue

        if parallel > 1:
            repo = git_helper.repo_root()
            # THE FACTORY MUST BE IN HEAD.
            #
            # The worktree is a checkout of HEAD. If `adws/` is not committed,
            # the checkout is born without the factory — no script, no modules,
            # no prompts — and each child dies in there for a different and
            # equally obscure reason ("No such file", "system prompt not found").
            # Finding that out cost two waves.
            #
            # The check happens here, once, before creating a worktree or paying
            # an agent. The installer already treats `adws/` as version
            # controlled; this only enforces what it presupposes.
            missing = [d for d in ("adws/adw_run.py", "adws/adw_modules", "adws/adw_data/prompt_engineering")
                       if not git_helper.tracked(d)]
            if missing:
                print(f"\n\033[31m✗ the factory is not committed — the worktree would be born without it.\033[0m\n"
                      f"  outside HEAD: {', '.join(missing)}\n\n"
                      f"  git add adws/ && git commit -m \"chore: version the factory\"\n\n"
                      f"  (or run with --parallel 1, which works in the main tree)",
                      file=sys.stderr)
                return 1
            # Absolute: the child runs in the worktree, and a relative `--config`
            # would point at THAT checkout's config — which may be stale.
            config = str((Path(config) if Path(config).is_absolute() else repo / config))
            branch = git_helper.current_branch()
            state = _isolated_wave(wave, repo, branch, config, extra or [], parallel)
            for t in wave:
                F.mark(t, state.get(t.number, F.FAILED))
            done_now += len(wave)
            if any(v == F.FAILED for v in state.values()):
                print(f"\n\033[31m✗ the wave did not close — the loop stops here.\033[0m\n"
                      f"  A ticket failed or did not integrate. What came back green IS ALREADY on\n"
                      f"  '{branch}': good work is not undone. Look at what is left,\n"
                      f"  fix it, set Status back to 'ready-for-agent' and run again.",
                      file=sys.stderr)
                return 1
            continue

        ticket = wave[0]
        code = _run_ticket(ticket, config, extra or [])
        F.mark(ticket, F.DONE if code == 0 else F.FAILED)
        done_now += 1
        if code != 0:
            print(f"\n\033[31m✗ #{ticket.number:02d} failed — the loop stops here.\033[0m\n"
                  f"  Look at the run before carrying on: a ticket that fails usually says the\n"
                  f"  spec or the split was wrong, and the ones depending on it would inherit that.\n"
                  f"  Fixed it? Set Status back to 'ready-for-agent' and run again.",
                  file=sys.stderr)
            return 1

    print(f"\n\033[33m⚠ ceiling of {limit} tickets reached — run again to continue\033[0m")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("issues", type=Path, help="the feature's issues/ directory")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, dest="limit")
    parser.add_argument("--dry", action="store_true", help="show the WAVES without spending anything")
    parser.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL,
                        help="simultaneous tickets per wave, each in its own worktree. "
                             "1 = sequential in the main tree, no isolation")
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("--no-checks", action="store_true", dest="no_checks",
                        help="passed through to each adw_run — project has no tests yet")
    args, unknown = parser.parse_known_args()
    passthrough = (["--no-checks"] if args.no_checks else []) + unknown
    sys.exit(main(args.issues, args.limit, args.dry, args.parallel, args.config, passthrough))
