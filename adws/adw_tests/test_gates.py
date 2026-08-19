"""The gates: what fails, and why.

A gate that approves what it should reject does not fail — it lets things
through, and the damage shows up stages later, far from its cause.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adw_modules import gates
from adw_modules.data_types import GenericOutput, Ticket, TicketsOutput


def env(*artifacts):
    return GenericOutput(status="success", artifacts=list(artifacts))


class TestHasSections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, text):
        p = self.dir / "doc.md"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def failures(self, report):
        return [c.item for c in report.checks if not c.ok]

    def test_a_section_present_and_with_content_passes(self):
        p = self.write("## Problem\none sentence\n\n## Solution\nanother\n")
        r = gates.has_sections("Problem", "Solution")(env(p), None)
        self.assertEqual(self.failures(r), [])

    def test_a_section_PRESENT_AND_EMPTY_fails(self):
        # The case the other gates do not catch: right shape, hollow content.
        p = self.write("## Problem\none sentence\n\n## Solution\n\n## End\nx\n")
        r = gates.has_sections("Problem", "Solution")(env(p), None)
        self.assertEqual(self.failures(r), ["doc.md § Solution"])

    def test_a_missing_section_fails(self):
        p = self.write("## Problem\nx\n")
        r = gates.has_sections("Problem", "Tests")(env(p), None)
        self.assertEqual(self.failures(r), ["doc.md § Tests"])

    def test_a_heading_at_any_level_counts(self):
        p = self.write("# Problem\nx\n\n### Solution\ny\n")
        r = gates.has_sections("Problem", "Solution")(env(p), None)
        self.assertEqual(self.failures(r), [])

    def test_a_missing_file_is_artifacts_exists_problem(self):
        r = gates.has_sections("Problem")(env(str(self.dir / "does-not-exist.md")), None)
        self.assertEqual(r.checks, [])


class TestDag(unittest.TestCase):
    def failures(self, tickets):
        r = gates.tickets_form_a_dag(TicketsOutput(status="success", tickets=tickets), None)
        return [c.item for c in r.checks if not c.ok]

    def t(self, n, b=()):
        return Ticket(number=n, title=f"t{n}", delivers="x", blocked_by=list(b))

    def test_a_healthy_chain_passes(self):
        self.assertEqual(self.failures([self.t(1), self.t(2, [1]), self.t(3, [2])]), [])

    def test_a_nonexistent_blocker_fails(self):
        self.assertIn("#2 blockers exist", self.failures([self.t(1), self.t(2, [9])]))

    def test_self_blocking_fails(self):
        self.assertIn("#2 does not block itself", self.failures([self.t(1), self.t(2, [2])]))

    def test_a_cycle_fails(self):
        self.assertIn("no cycles", self.failures([self.t(1), self.t(2, [3]), self.t(3, [2])]))

    def test_everything_blocked_fails_for_having_nowhere_to_start(self):
        self.assertIn("something can start now", self.failures([self.t(1, [2]), self.t(2, [1])]))

    def test_out_of_order_fails(self):
        self.assertIn("#1 numbered after its blockers", self.failures([self.t(1, [2]), self.t(2)]))

    def test_an_empty_list_fails(self):
        self.assertIn("tickets", self.failures([]))

    def test_the_note_describes_the_FINDING_in_both_cases(self):
        # A ✓ next to "blocks itself" is a trace that lies about what passed.
        r = gates.tickets_form_a_dag(
            TicketsOutput(status="success", tickets=[self.t(1)]), None)
        note = next(c.note for c in r.checks if "block itself" in c.item)
        self.assertEqual(note, "does not")


class TestNotionalPricing(unittest.TestCase):
    """Estimated cost: it exists to COMPARE runs, never to add up on an invoice."""

    def setUp(self):
        from adw_modules import pricing
        self.pricing = pricing
        self.usage = {"input": 1000, "output": 1000, "cacheRead": 1000, "cacheWrite": 1000}

    def test_estimates_by_the_models_prefix(self):
        self.assertAlmostEqual(self.pricing.estimate("claude-sonnet-5", self.usage),
                               (3 + 15 + 0.3 + 3.75) / 1000, places=6)

    def test_opus_costs_more_than_sonnet_which_costs_more_than_haiku(self):
        p = self.pricing.estimate
        self.assertGreater(p("claude-opus-5", self.usage), p("claude-sonnet-5", self.usage))
        self.assertGreater(p("claude-sonnet-5", self.usage), p("claude-haiku-4-5", self.usage))

    def test_an_UNKNOWN_model_returns_zero_instead_of_guessing(self):
        # An invented average price would enter the trace looking measured, which
        # is worse than having no number at all.
        self.assertEqual(self.pricing.estimate("gpt-5.6-luna", self.usage), 0.0)
        self.assertEqual(self.pricing.estimate("model-that-does-not-exist", self.usage), 0.0)

    def test_an_empty_usage_does_not_blow_up(self):
        self.assertEqual(self.pricing.estimate("claude-opus-5", {}), 0.0)

    def test_a_provider_charge_takes_precedence_over_the_estimate(self):
        from adw_modules.data_types import UsageBreakdown
        u = UsageBreakdown()
        u.add_turn({"input": 10, "cost": {"total": 0.5}}, 10, estimated=99.0)
        self.assertEqual(u.total_cost, 0.5)
        self.assertEqual(u.estimated_cost, 0.0)     # nothing was estimated here

    def test_without_a_charge_the_estimate_lands_and_stays_MARKED(self):
        from adw_modules.data_types import UsageBreakdown
        u = UsageBreakdown()
        u.add_turn({"input": 10, "cost": {"total": 0}}, 10, estimated=0.25)
        self.assertEqual(u.total_cost, 0.25)
        self.assertEqual(u.estimated_cost, 0.25)    # and the trace knows it is an estimate


if __name__ == "__main__":
    unittest.main(verbosity=2)
