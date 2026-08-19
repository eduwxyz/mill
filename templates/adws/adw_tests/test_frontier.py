"""The frontier and the blocking graph: what decides the ORDER of everything.

A mistake here does not show up as an error — it shows up as a ticket built too
early, on top of code that does not exist yet, and the damage is only seen after
the agent has been paid for.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import frontier as F


def ticket(dirpath: Path, number: int, blocked: str = "None — can start immediately.",
           status: str = F.READY) -> Path:
    path = dirpath / f"{number:02d}-t{number}.md"
    path.write_text(
        f"# {number:02d} — t{number}\n\n"
        f"**What to build:** nothing.\n\n"
        f"**Blocked by:** {blocked}\n\n"
        f"**Status:** {status}\n\n- [ ] criterion\n", encoding="utf-8")
    return path


class TestReading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_reads_number_status_and_blockers(self):
        ticket(self.dir, 1)
        ticket(self.dir, 2, blocked="01 — t1.")
        ts = F.load(self.dir)
        self.assertEqual([t.number for t in ts], [1, 2])
        self.assertEqual(ts[0].blocked_by, [])
        self.assertEqual(ts[1].blocked_by, [1])

    def test_none_in_any_form_means_unblocked(self):
        for text in ("None — can start immediately.", "None", "none."):
            with self.subTest(text):
                d = Path(tempfile.mkdtemp())
                ticket(d, 1, blocked=text)
                self.assertEqual(F.load(d)[0].blocked_by, [])

    def test_several_blockers_with_titles(self):
        ticket(self.dir, 3, blocked="01 — does X; 02 — does Y.")
        self.assertEqual(F.load(self.dir)[0].blocked_by, [1, 2])

    def test_ignores_a_file_without_a_number(self):
        ticket(self.dir, 1)
        (self.dir / "README.md").write_text("notes", encoding="utf-8")
        self.assertEqual(len(F.load(self.dir)), 1)

    def test_a_ticket_does_not_block_itself_even_if_the_text_says_so(self):
        # The title beside the number usually repeats the ticket's own name;
        # reading that as self-blocking would keep the ticket permanently out of
        # the frontier.
        ticket(self.dir, 2, blocked="02 — t2.")
        self.assertEqual(F.load(self.dir)[0].blocked_by, [])


class TestFrontier(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_only_the_unblocked_gets_in(self):
        ticket(self.dir, 1)
        ticket(self.dir, 2, blocked="01 — t1.")
        self.assertEqual([t.number for t in F.frontier(F.load(self.dir))], [1])

    def test_complete_releases_whoever_depended_on_it(self):
        ticket(self.dir, 1, status=F.DONE)
        ticket(self.dir, 2, blocked="01 — t1.")
        self.assertEqual([t.number for t in F.frontier(F.load(self.dir))], [2])

    def test_the_wave_brings_every_released_ticket_together(self):
        ticket(self.dir, 1, status=F.DONE)
        ticket(self.dir, 2, blocked="01 — t1.")
        ticket(self.dir, 3, blocked="01 — t1.")
        self.assertEqual([t.number for t in F.frontier(F.load(self.dir))], [2, 3])

    def test_a_blocker_that_FAILED_releases_nobody(self):
        # The point of "stop on the first failure": carrying on builds on top of
        # the defect.
        ticket(self.dir, 1, status=F.FAILED)
        ticket(self.dir, 2, blocked="01 — t1.")
        self.assertEqual(F.frontier(F.load(self.dir)), [])

    def test_a_failed_ticket_does_not_return_to_the_frontier_on_its_own(self):
        ticket(self.dir, 1, status=F.FAILED)
        self.assertEqual(F.frontier(F.load(self.dir)), [])

    def test_a_cycle_leaves_the_frontier_empty_without_hanging(self):
        ticket(self.dir, 1, blocked="02 — t2.")
        ticket(self.dir, 2, blocked="01 — t1.")
        self.assertEqual(F.frontier(F.load(self.dir)), [])


class TestMarking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_marking_preserves_the_rest_of_the_file(self):
        path = ticket(self.dir, 1)
        before = path.read_text(encoding="utf-8")
        t = F.load(self.dir)[0]
        F.mark(t, F.DONE)
        after = path.read_text(encoding="utf-8")
        self.assertIn("**Status:** done", after)
        self.assertIn("- [ ] criterion", after)          # the body survives
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))

    def test_marking_then_re_reading_gives_the_new_state(self):
        ticket(self.dir, 1)
        F.mark(F.load(self.dir)[0], F.DONE)
        self.assertTrue(F.load(self.dir)[0].done)

    def test_a_ticket_without_a_status_line_gets_one(self):
        path = self.dir / "01-no-status.md"
        path.write_text("# 01 — x\n\n**Blocked by:** None\n", encoding="utf-8")
        F.mark(F.load(self.dir)[0], F.DONE)
        self.assertIn("**Status:** done", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
