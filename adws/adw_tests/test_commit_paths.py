"""`commit_paths`: what goes into the ticket's commit, and what stays out.

The defect that produced this: the engineer had 16 files in progress when they
fired the first run, and `commit_all` (`git add -A`) would have swept their work
into the ticket's commit. Nothing would have been lost — but the commit would
have mixed two unrelated things, and separating them afterwards is tedious.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import git_helper


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout


class TestCommitPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.previous_cwd = Path.cwd()
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("config", "user.email", "t@t", cwd=self.repo)
        git("config", "user.name", "t", cwd=self.repo)
        (self.repo / "mine.py").write_text("my work\n")
        (self.repo / "other.py").write_text("x\n")
        git("add", "-A", cwd=self.repo); git("commit", "-qm", "initial", cwd=self.repo)
        os.chdir(self.repo)                       # git_helper operates on the cwd
        self.addCleanup(self.restore)

    def restore(self):
        os.chdir(self.previous_cwd)
        self.tmp.cleanup()

    def dirty(self):
        return {l[3:] for l in git("status", "--porcelain", cwd=self.repo).splitlines() if l}

    def in_commit(self):
        return set(git("show", "--name-only", "--format=", "HEAD", cwd=self.repo).split())

    def test_commits_only_the_requested_path_and_preserves_the_rest(self):
        (self.repo / "mine.py").write_text("my work IN PROGRESS\n")   # their dirt
        (self.repo / "agent.py").write_text("from the agent\n")
        git_helper.commit_paths("feat: from the agent", ["agent.py"])
        self.assertEqual(self.in_commit(), {"agent.py"})
        self.assertEqual(self.dirty(), {"mine.py"})       # their work stays OUT

    def test_a_file_deleted_by_the_agent_enters_the_commit(self):
        # Without `git rm --cached` the removal is left out and reappears in the
        # tree as pending forever.
        (self.repo / "other.py").unlink()
        git_helper.commit_paths("chore: remove other", ["other.py"])
        self.assertEqual(self.in_commit(), {"other.py"})
        self.assertEqual(self.dirty(), set())

    def test_an_empty_list_is_an_error_with_a_reason(self):
        with self.assertRaises(RuntimeError) as e:
            git_helper.commit_paths("nothing", [])
        self.assertIn("nothing to commit", str(e.exception))

    def test_a_path_with_no_real_change_is_a_named_error(self):
        # A run that passed because the behaviour already existed: there is
        # nothing to commit, and saying so beats a generic "nothing to commit".
        with self.assertRaises(RuntimeError) as e:
            git_helper.commit_paths("nothing changed", ["mine.py"])
        self.assertIn("already match HEAD", str(e.exception))

    def test_several_paths_at_once(self):
        (self.repo / "a.py").write_text("a\n")
        (self.repo / "b.py").write_text("b\n")
        (self.repo / "mine.py").write_text("touched\n")
        git_helper.commit_paths("feat: two", ["a.py", "b.py"])
        self.assertEqual(self.in_commit(), {"a.py", "b.py"})
        self.assertEqual(self.dirty(), {"mine.py"})

    def test_outside_a_repository_it_says_what_to_do(self):
        empty = tempfile.mkdtemp()
        os.chdir(empty)
        with self.assertRaises(RuntimeError) as e:
            git_helper.commit_paths("x", ["a.py"])
        self.assertIn("git init", str(e.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
