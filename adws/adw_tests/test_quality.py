"""`run_quality` runs what THIS project declares — not a fixed list.

The defect that produced this: `run_quality` called a fixed `[test, lint,
typecheck, build]`, from when all four always existed as placeholders. After
detection started including only what the repository announces, a project with
only `test` made `lint()` raise StopIteration — whose `str()` is EMPTY.

The result on screen: criterion passed, test passed, and the `verify` phase
failed with `error: ""`. The engineer lost two paid runs hunting for a defect in
code that did not exist.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import quality


class FakeRun(SimpleNamespace):
    """The minimum `_specs` and `_run` touch."""


def run_in(repo: Path):
    phases = [SimpleNamespace(seq=1, phase_id="p1")]
    return FakeRun(
        repo_root=repo, phases=phases,
        context_handoff_dir=repo / ".handoff",
        console=SimpleNamespace(note=lambda *a, **k: None),
        adw_id="test",
        tracer=SimpleNamespace(event=lambda *a, **k: None),
    )


class TestOpportunisticChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".handoff").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def specs(self, repo):
        return [s.name for s in quality._specs(run_in(repo))]

    def test_a_project_with_NOTHING_still_declares_test(self):
        # `test` is mandatory: undetected it becomes a placeholder, and a
        # placeholder makes the run refuse before spending. Dropping it would be
        # the dangerous silence.
        self.assertEqual(self.specs(self.repo), ["test"])

    def test_a_project_with_only_test_DOES_NOT_declare_lint(self):
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "a_test.py").write_text("")
        self.assertEqual(self.specs(self.repo), ["test"])

    def test_run_quality_DOES_NOT_blow_up_when_there_is_only_test(self):
        # The exact case from genai/token-observability: the defect brought the
        # verify phase down AFTER the criterion and the test had passed.
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "a_test.py").write_text("")
        result = quality.run_quality(run_in(self.repo))
        self.assertEqual([c.name for c in result.checks], ["test"])

    def test_a_node_project_declares_what_it_has(self):
        (self.repo / "package.json").write_text('{"scripts":{"test":"bun test","lint":"eslint ."}}')
        (self.repo / "bun.lock").write_text("")
        (self.repo / "tsconfig.json").write_text("{}")
        self.assertEqual(sorted(self.specs(self.repo)), ["lint", "test", "typecheck"])

    def test_a_nonexistent_check_fails_WITH_A_MESSAGE(self):
        # StopIteration has an empty str(); an error without a message burns the
        # time of whoever is looking without pointing at anything.
        with self.assertRaises(RuntimeError) as e:
            quality._spec(run_in(self.repo), "lint")
        self.assertIn("does not exist in this project", str(e.exception))
        self.assertIn("detected:", str(e.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
