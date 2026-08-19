"""`snapshot` has to see the REWRITE of an untracked file.

The defect: untracked files were fingerprinted by name alone, as `"untracked"`.
An agent that rewrote an already-existing file produced the same fingerprint
before and after — and the run concluded that nothing had changed.

In a NEW repository this is guaranteed: everything is untracked, so a ticket's
second attempt always ended in "nothing to commit", with the work finished on
disk and no commit. It cost three paid runs.
"""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import permissions


class TestSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *args], cwd=self.repo, capture_output=True)
        (self.repo / "tracked.py").write_text("base\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "i"], cwd=self.repo, capture_output=True)
        self.run = SimpleNamespace(repo_root=self.repo)
        self.addCleanup(self.tmp.cleanup)

    def test_a_new_file_shows_up(self):
        before = permissions.snapshot(self.run)
        (self.repo / "new.md").write_text("x\n")
        after = permissions.snapshot(self.run)
        self.assertIn("new.md", permissions.changed_paths(before, after))

    def test_the_REWRITE_of_an_untracked_file_shows_up(self):
        # The exact defect: the file already exists (from a previous attempt) and
        # the agent rewrites it. Before, that was invisible.
        (self.repo / "doc.md").write_text("first version\n")
        before = permissions.snapshot(self.run)
        time.sleep(0.01)
        (self.repo / "doc.md").write_text("second version, quite different\n")
        after = permissions.snapshot(self.run)
        self.assertIn("doc.md", permissions.changed_paths(before, after))

    def test_a_rewrite_of_the_SAME_SIZE_also_shows_up(self):
        # Size alone would not be enough — hence the mtime alongside it.
        (self.repo / "doc.md").write_text("aaaa\n")
        before = permissions.snapshot(self.run)
        time.sleep(0.01)
        (self.repo / "doc.md").write_text("bbbb\n")
        after = permissions.snapshot(self.run)
        self.assertIn("doc.md", permissions.changed_paths(before, after))

    def test_an_untouched_file_does_NOT_show_up(self):
        (self.repo / "doc.md").write_text("x\n")
        before = permissions.snapshot(self.run)
        after = permissions.snapshot(self.run)
        self.assertEqual(permissions.changed_paths(before, after), [])

    def test_an_edit_to_a_tracked_file_shows_up(self):
        before = permissions.snapshot(self.run)
        (self.repo / "tracked.py").write_text("base\nmore\n")
        after = permissions.snapshot(self.run)
        self.assertIn("tracked.py", permissions.changed_paths(before, after))

    def test_a_DELETED_file_shows_up(self):
        (self.repo / "doc.md").write_text("x\n")
        before = permissions.snapshot(self.run)
        (self.repo / "doc.md").unlink()
        after = permissions.snapshot(self.run)
        self.assertIn("doc.md", permissions.changed_paths(before, after))


if __name__ == "__main__":
    unittest.main(verbosity=2)
