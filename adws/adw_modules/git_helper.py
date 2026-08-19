"""Low-level git operations for code phases. All low-level logic lives in adw_modules."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def create_branch(name: str) -> str:
    _git("checkout", "-b", name)
    return name


def is_repo() -> bool:
    result = subprocess.run(["git", "rev-parse", "--git-dir"],
                            capture_output=True, text=True)
    return result.returncode == 0


def repo_root() -> Path:
    """Absolute root of the codebase — where agents are spawned to work.

    The git toplevel when there is one, else the process cwd (ADWs run fine in a
    non-git dir; only a commit phase requires a repo). Always absolute, so it is
    safe to hand to a subprocess regardless of where the ADW was launched from.
    """
    if is_repo():
        return Path(_git("rev-parse", "--show-toplevel")).resolve()
    return Path.cwd().resolve()


def commit_paths(message: str, paths: list[str]) -> str:
    """Commit ONLY these paths, leaving the rest of the tree as it was.

    `commit_all` swept everything with `git add -A`, and in a repository where the
    engineer has work in progress that sweeps their work along with it — under the
    ticket's message. Nothing is lost, but it becomes a commit that mixes two
    unrelated things, and separating them afterwards is tedious.

    The paths come from `permissions.enforce`, which already compares the change
    set before and after every agent to decide what to revert. In other words, the
    run ALWAYS knew what it touched; it was simply throwing that away.

    A LIMIT THAT CANNOT BE WORKED AROUND HERE: if an agent edited a file that was
    already dirty, the commit takes both changes together — git commits files, not
    fragments. An isolated worktree is what actually solves that.
    """
    if not is_repo():
        raise RuntimeError(
            "not a git repository — a commit phase needs one. Run `git init` in the "
            "repo root (and make a first commit) before running an ADW that commits.")
    if not paths:
        raise RuntimeError("nothing to commit — the preceding phases changed no files")
    existing = [p for p in paths if Path(p).exists()]
    missing = [p for p in paths if not Path(p).exists()]
    _git("add", "--", *existing) if existing else None
    # A deletion by an agent is a change too: without this the removal is left out
    # of the commit and reappears in the tree as pending forever.
    for path in missing:
        _git("rm", "--cached", "--ignore-unmatch", "--", path)
    staged = _git("diff", "--cached", "--name-only")
    if not staged:
        raise RuntimeError(
            f"nothing to commit — the {len(paths)} path(s) the agents touched "
            f"already match HEAD")
    _git("commit", "-m", message)
    return _git("rev-parse", "--short", "HEAD")


def commit_all(message: str) -> str:
    """Stage the working tree and commit it. Returns the new short sha."""
    if not is_repo():
        raise RuntimeError(
            "not a git repository — a commit phase needs one. Run `git init` in the "
            "repo root (and make a first commit) before running an ADW that commits.")
    _git("add", "-A")
    if not _git("status", "--porcelain"):
        raise RuntimeError("nothing to commit — the preceding phases changed no files")
    _git("commit", "-m", message)
    return _git("rev-parse", "--short", "HEAD")


def tracked(path: str) -> bool:
    """Does this path exist in HEAD? — the question that decides whether a worktree will have it."""
    out = subprocess.run(["git", "ls-tree", "--name-only", "HEAD", path],
                         capture_output=True, text=True)
    return out.returncode == 0 and bool(out.stdout.strip())


def changed_files() -> list[str]:
    out = _git("status", "--porcelain")
    return [line[3:] for line in out.splitlines() if line]


# ── diff plumbing (composed into a ChangeSet by documentation.py) ────────────

def ref_exists(ref: str) -> bool:
    """True when `ref` resolves to a commit. Never raises — this is a question."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                            capture_output=True, text=True)
    return result.returncode == 0


def rev(ref: str = "HEAD") -> str:
    return _git("rev-parse", ref)


def short_sha(ref: str = "HEAD") -> str:
    return _git("rev-parse", "--short", ref)


def merge_base(ref: str, other: str = "HEAD") -> str:
    """The commit where `ref` and `other` diverged — the honest base of a branch.

    On the base branch itself this returns HEAD, which makes the diff exactly
    "what is not committed yet". Off it, the diff is the whole branch plus the
    working tree. One command covers both cases, so no ADW has to branch on it.
    """
    return _git("merge-base", ref, other)


def is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def untracked_files() -> list[str]:
    out = _git("ls-files", "--others", "--exclude-standard")
    return [line for line in out.splitlines() if line]


def diff_files(base: str) -> list[str]:
    """Tracked files that differ between `base` and the working tree."""
    out = _git("diff", "--name-only", base)
    return [line for line in out.splitlines() if line]


def diff_stat(base: str) -> str:
    return _git("diff", "--stat", base)


def diff_counts(base: str) -> tuple[int, int]:
    """(insertions, deletions) across the diff. Binary files count as neither."""
    insertions = deletions = 0
    for line in _git("diff", "--numstat", base).splitlines():
        added, removed, *_ = line.split("\t")
        if added.isdigit():
            insertions += int(added)
        if removed.isdigit():
            deletions += int(removed)
    return insertions, deletions


def diff_text(base: str) -> str:
    return _git("diff", base)
