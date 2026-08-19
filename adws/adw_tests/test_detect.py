"""Check detection: what the repository already announces about itself.

The dangerous failure mode here is the FALSE POSITIVE — detecting a test command
that does not test the project. Then the run believes it has a safety net, and it
does not.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules.detect import detect_checks, missing_mandatory


class TestDetect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, content=""):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_an_empty_repo_detects_nothing_and_SAYS_SO(self):
        # Silence here would be the dangerous outcome: a project with no check and
        # no complaint is a project building on nothing.
        self.assertEqual(detect_checks(self.repo), {})
        self.assertEqual(missing_mandatory(detect_checks(self.repo)), ["test"])

    def test_THE_FACTORY_IS_NOT_THE_PROJECT(self):
        # `adw_build_test.py` and `adw_plan_build_test.py` match `*_test.py`.
        # Without excluding `adws/`, a freshly installed and EMPTY repo "detected"
        # unittest — the factory testing itself in place of the engineer's code.
        self.write("adws/adw_build_test.py", "x")
        self.write("adws/adw_plan_build_test.py", "x")
        self.assertEqual(detect_checks(self.repo), {})

    def test_bun_with_a_test_script(self):
        self.write("package.json", '{"scripts":{"test":"bun test"}}')
        self.write("bun.lock", "")
        self.assertEqual(detect_checks(self.repo)["test"], ["bun", "run", "test"])

    def test_npm_without_a_bun_lockfile(self):
        self.write("package.json", '{"scripts":{"test":"jest"}}')
        self.assertEqual(detect_checks(self.repo)["test"], ["npm", "test"])

    def test_tsconfig_turns_the_typecheck_on(self):
        self.write("package.json", '{"scripts":{"test":"bun test"}}')
        self.write("bun.lock", ""); self.write("tsconfig.json", "{}")
        self.assertEqual(detect_checks(self.repo)["typecheck"], ["bunx", "tsc", "--noEmit"])

    def test_bun_without_a_script_but_with_test_files(self):
        self.write("package.json", "{}"); self.write("bun.lock", "")
        self.write("src/sum.test.ts", "")
        self.assertEqual(detect_checks(self.repo)["test"], ["bun", "test"])

    def test_python_with_a_pyproject(self):
        self.write("pyproject.toml", "[project]\nname='x'\n")
        self.assertEqual(detect_checks(self.repo)["test"], ["pytest", "-q"])

    def test_ruff_in_the_pyproject_turns_the_lint_on(self):
        self.write("pyproject.toml", "[tool.ruff]\nline-length=100\n")
        self.assertEqual(detect_checks(self.repo)["lint"], ["ruff", "check", "."])

    def test_python_without_a_pyproject_falls_back_to_stdlib_unittest(self):
        self.write("tests/sum_test.py", "")
        self.assertIn("unittest", detect_checks(self.repo)["test"])

    def test_go_and_rust_by_their_project_file(self):
        self.write("go.mod", "module x")
        self.assertEqual(detect_checks(self.repo)["test"], ["go", "test", "./..."])
        (self.repo / "go.mod").unlink()
        self.write("Cargo.toml", "[package]")
        self.assertEqual(detect_checks(self.repo)["test"], ["cargo", "test"])

    def test_a_detected_test_means_nothing_is_missing(self):
        self.write("go.mod", "module x")
        self.assertEqual(missing_mandatory(detect_checks(self.repo)), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
