"""Worktrees: every ticket builds in its own checkout, and integration is explicit.

The gain is parallelism, but the reason is isolation. Two `adw_run`s in the same
working tree would commit each other's code, and one's `verify` would see the
other's half-way state — a green that proves nothing.

**The order is: parallelize within a wave, integrate between waves.** Every
ticket unblocked at that moment starts from the SAME commit and works isolated;
when they all finish, whatever came back green is merged, one at a time, and only
then is the next wave computed. That way a ticket never builds on top of code
that does not exist yet, and a conflict, when it appears, appears at integration
— where there is a human to look at it — instead of inside an agent.

NOTHING HERE RESOLVES A CONFLICT. A merge that conflicts is aborted whole and the
loop stops. An agent resolving a conflict on its own is the most expensive way to
lose code: the damage hides inside a merge nobody read.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BRANCH_PREFIX = "mill"


def _git(*args: str, cwd: Path | str | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip() or out.stdout.strip()}")
    return out.stdout.strip()


def _try(*args: str, cwd: Path | str | None = None) -> tuple[int, str]:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.returncode, (out.stderr + out.stdout).strip()


@dataclass
class Worktree:
    number: int
    branch: str
    path: Path


def root(repo: Path) -> Path:
    """Outside the repository, on purpose.

    A worktree inside the tree becomes an untracked file that shows up in
    everyone's `git status`, gets swept into a distracted `git add -A`, and is
    wiped by a `clean -fd`. Outside, it is invisible to the repo and disappears
    with one command.
    """
    return repo.parent / f".{repo.name}-mill-worktrees"


def create(repo: Path, number: int, slug: str, base: str) -> Worktree:
    """A clean checkout at `base`, on a new branch. Reuses nothing."""
    branch = f"{BRANCH_PREFIX}/{number:02d}-{slug}"
    path = root(repo) / f"{number:02d}-{slug}"

    # Leftovers from a previous execution (interrupted, killed) are removed
    # rather than reused: a half-built worktree is worse than none, because the
    # build happens and nobody knows what it happened on top of.
    remove(repo, Worktree(number, branch, path), force=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--detach", str(path), base, cwd=repo)
    _git("switch", "-c", branch, cwd=path)
    return Worktree(number, branch, path)


def remove(repo: Path, wt: Worktree, force: bool = False) -> None:
    """Deletes the checkout and the branch. `force` swallows absence, for cleanup."""
    code, _ = _try("worktree", "remove", "--force", str(wt.path), cwd=repo)
    if code != 0 and wt.path.exists() and force:
        shutil.rmtree(wt.path, ignore_errors=True)
    _try("worktree", "prune", cwd=repo)
    _try("branch", "-D", wt.branch, cwd=repo)


def has_commits(repo: Path, wt: Worktree, base: str) -> bool:
    """Did the run commit anything on that branch?

    The question is worth asking: a run that passed everything and committed
    nothing does exist — the criterion may have been satisfied by what was
    already there. Merging an empty branch breaks nothing, but it dirties the
    history with a merge that says nothing.
    """
    code, out = _try("rev-list", "--count", f"{base}..{wt.branch}", cwd=repo)
    return code == 0 and out.isdigit() and int(out) > 0


def merge(repo: Path, wt: Worktree, into: str) -> tuple[bool, str]:
    """Merges the ticket's branch. A conflict ABORTS and returns the reason.

    `--no-ff` on purpose: the merge stays in the history as an event, and the
    whole ticket can be undone with a `revert -m 1`. Fast-forward would dissolve
    the ticket into the timeline and take that handle away.
    """
    current = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo)
    if current != into:
        return False, f"the main tree is on '{current}', and integration would be into '{into}'"

    code, out = _try("merge", "--no-ff", "--no-edit", "-m",
                     f"mill: integrate #{wt.number:02d} ({wt.branch})", wt.branch, cwd=repo)
    if code == 0:
        return True, _git("rev-parse", "--short", "HEAD", cwd=repo)

    # Aborts whole. Half a merge in the engineer's tree is worse than none: their
    # next command happens in a state they did not choose.
    _try("merge", "--abort", cwd=repo)
    # Git's first line is "Auto-merging <file>" — the step that worked before the
    # one that failed. What needs to surface is the CONFLICT, with its files.
    conflicts = [l for l in out.splitlines() if "CONFLICT" in l or "conflict" in l.lower()]
    files = sorted({l.split(" in ")[-1].strip() for l in out.splitlines() if "CONFLICT" in l})
    if conflicts:
        return False, (f"conflict in {', '.join(files)}" if files else conflicts[0])
    return False, out.splitlines()[-1] if out else "merge refused"
