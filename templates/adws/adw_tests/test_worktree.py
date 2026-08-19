"""Worktrees and integration: the part that touches the engineer's repository.

Every test here runs against a REAL git in a temporary directory. A git mock
would prove that my mental model is consistent with itself, which is exactly what
is not in doubt — what is in doubt is git.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import worktree as W


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "project"
        self.repo.mkdir()
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "t@t", cwd=self.repo)
        git("config", "user.name", "t", cwd=self.repo)
        (self.repo / "app.py").write_text("base = 1\n")
        git("add", "-A", cwd=self.repo); git("commit", "-qm", "initial", cwd=self.repo)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for line in git("worktree", "list", "--porcelain", cwd=self.repo).stdout.splitlines():
            if line.startswith("worktree ") and "project" not in line:
                git("worktree", "remove", "--force", line.split(" ", 1)[1], cwd=self.repo)
        self.tmp.cleanup()

    def head(self):
        return git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def dirty(self):
        return bool(git("status", "--porcelain", cwd=self.repo).stdout.strip())

    def commit_in(self, wt, filename, content):
        (wt.path / filename).write_text(content)
        git("add", "-A", cwd=wt.path)
        git("commit", "-qm", f"change {filename}", cwd=wt.path)


class TestCreation(Repo):
    def test_a_worktree_is_born_outside_the_repository(self):
        # Inside, it would become an untracked file: it shows up in everyone's
        # status, gets swept into a distracted `add -A`, and disappears in a
        # `clean -fd`.
        wt = W.create(self.repo, 1, "x", self.head())
        self.assertNotIn(str(self.repo), str(wt.path.parent.resolve()))
        self.assertFalse(self.dirty())
        W.remove(self.repo, wt)

    def test_it_starts_from_the_requested_commit_on_a_branch_of_its_own(self):
        wt = W.create(self.repo, 1, "x", self.head())
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt.path).stdout.strip(), self.head())
        self.assertEqual(git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt.path).stdout.strip(),
                         wt.branch)
        W.remove(self.repo, wt)

    def test_a_leftover_from_a_previous_run_is_discarded_not_reused(self):
        first = W.create(self.repo, 1, "x", self.head())
        (first.path / "junk.py").write_text("half a build\n")
        second = W.create(self.repo, 1, "x", self.head())        # same number
        self.assertFalse((second.path / "junk.py").exists())
        W.remove(self.repo, second)

    def test_remove_deletes_the_checkout_and_the_branch(self):
        wt = W.create(self.repo, 1, "x", self.head())
        W.remove(self.repo, wt)
        self.assertFalse(wt.path.exists())
        self.assertNotIn(wt.branch, git("branch", "--list", cwd=self.repo).stdout)


class TestIntegration(Repo):
    def test_two_in_different_files_both_integrate(self):
        base = self.head()
        a, b = W.create(self.repo, 1, "a", base), W.create(self.repo, 2, "b", base)
        self.commit_in(a, "a.py", "a\n"); self.commit_in(b, "b.py", "b\n")
        self.assertTrue(W.merge(self.repo, a, "main")[0])
        self.assertTrue(W.merge(self.repo, b, "main")[0])
        self.assertTrue((self.repo / "a.py").exists() and (self.repo / "b.py").exists())
        W.remove(self.repo, a); W.remove(self.repo, b)

    def test_a_conflict_ABORTS_and_leaves_the_tree_clean(self):
        # The case that matters most: half a merge in the engineer's tree is worse
        # than none, because their next command happens in a state they did not
        # choose.
        base = self.head()
        a, b = W.create(self.repo, 1, "a", base), W.create(self.repo, 2, "b", base)
        self.commit_in(a, "app.py", "base = 1\nversion = 'A'\n")
        self.commit_in(b, "app.py", "base = 1\nversion = 'B'\n")
        self.assertTrue(W.merge(self.repo, a, "main")[0])
        ok, reason = W.merge(self.repo, b, "main")
        self.assertFalse(ok)
        self.assertIn("app.py", reason)                  # names the file
        self.assertFalse(self.dirty())                   # nothing half-done
        self.assertIn("version = 'A'", (self.repo / "app.py").read_text())
        W.remove(self.repo, a); W.remove(self.repo, b)

    def test_a_conflict_preserves_the_branch_for_you_to_resolve(self):
        base = self.head()
        a, b = W.create(self.repo, 1, "a", base), W.create(self.repo, 2, "b", base)
        self.commit_in(a, "app.py", "x\n"); self.commit_in(b, "app.py", "y\n")
        W.merge(self.repo, a, "main"); W.merge(self.repo, b, "main")
        self.assertIn(b.branch, git("branch", "--list", cwd=self.repo).stdout)
        self.assertTrue(b.path.exists())
        W.remove(self.repo, a); W.remove(self.repo, b)

    def test_merge_refuses_if_the_tree_changed_branch(self):
        # Integrating into the wrong branch is silent damage: the commit vanishes
        # from the engineer's view with no error at all.
        wt = W.create(self.repo, 1, "a", self.head())
        self.commit_in(wt, "a.py", "a\n")
        git("switch", "-qc", "other", cwd=self.repo)
        ok, reason = W.merge(self.repo, wt, "main")
        self.assertFalse(ok)
        self.assertIn("other", reason)
        W.remove(self.repo, wt)

    def test_no_ff_keeps_the_whole_ticket_revertible(self):
        wt = W.create(self.repo, 1, "a", self.head())
        self.commit_in(wt, "a.py", "a\n")
        W.merge(self.repo, wt, "main")
        parents = git("rev-list", "--parents", "-n", "1", "HEAD", cwd=self.repo).stdout.split()
        self.assertEqual(len(parents), 3, "the merge must have TWO parents — no fast-forward")
        W.remove(self.repo, wt)

    def test_has_commits_tells_who_produced_something_from_who_did_not(self):
        base = self.head()
        empty = W.create(self.repo, 1, "empty", base)
        full = W.create(self.repo, 2, "full", base)
        self.commit_in(full, "new.py", "x\n")
        self.assertFalse(W.has_commits(self.repo, empty, base))
        self.assertTrue(W.has_commits(self.repo, full, base))
        W.remove(self.repo, empty); W.remove(self.repo, full)


if __name__ == "__main__":
    unittest.main(verbosity=2)
