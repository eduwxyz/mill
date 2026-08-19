"""Validation gates: verify the envelope's CLAIMS, never guesses.

A gate is `gate(envelope, run) -> GateReport` — one check per item it looked at.
Violations are derived from the failed checks and sent back to the SAME agent
session as a correction. Every check is recorded either way, so a green gate
says WHAT it verified instead of only that it passed.

Gates check what is mechanically checkable; plan quality is a reviewer's job.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .data_types import EnvelopeBase, GateReport

TAIL_CHARS = 1000        # command output kept as evidence on a failure


def _size(path: Path) -> str:
    n = path.stat().st_size
    return f"{n}B" if n < 1024 else f"{n / 1024:.1f}KB"


def artifacts_exist(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        report.check(a, p.exists(),
                     f"exists, {_size(p)}" if p.exists() else "declared artifact does not exist")
    return report


def files_non_empty(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        if not (p.exists() and p.is_file()):
            continue                       # existence is artifacts_exist's job
        empty = p.stat().st_size == 0
        report.check(a, not empty, "declared artifact is empty" if empty else _size(p))
    return report


def json_parses(envelope: EnvelopeBase, run) -> GateReport:
    report = GateReport()
    for a in envelope.artifacts:
        p = Path(a)
        if p.suffix != ".json" or not p.exists():
            continue
        try:
            parsed = json.loads(p.read_text())
            report.check(a, True, f"parses, {type(parsed).__name__}")
        except json.JSONDecodeError as e:
            report.check(a, False, f"declared JSON artifact does not parse: {e}")
    return report


def diff_matches_claims(envelope: EnvelopeBase, run) -> GateReport:
    """Every file claimed changed must exist on disk."""
    report = GateReport()
    for f in getattr(envelope, "changed_files", []):
        p = Path(f)
        report.check(f, p.exists(),
                     f"exists, {_size(p)}" if p.exists() else "claimed changed file does not exist")
    return report


def verdict_consistent(envelope: EnvelopeBase, run) -> GateReport:
    """A review's verdict must agree with the findings it just wrote down.

    Nothing here judges the code — that is the reviewer's job. This checks the
    envelope against itself: an approval that ships blocking items, or a
    rejection that names no problem, is a claim the harness can refute without
    reading a line of the diff.
    """
    report = GateReport()
    approved = bool(getattr(envelope, "approved", False))
    blocking = list(getattr(envelope, "blocking", []))
    unmet = [f.requirement for f in getattr(envelope, "findings", []) if not f.met]

    report.check("approved vs blocking", not (approved and blocking),
                 "no blocking items" if not blocking
                 else f"{len(blocking)} blocking item(s) while approved=true"
                 if approved else f"{len(blocking)} blocking item(s), not approved")
    report.check("approved vs findings", not (approved and unmet),
                 "every requirement met" if not unmet
                 else f"{len(unmet)} unmet requirement(s) while approved=true"
                 if approved else f"{len(unmet)} unmet requirement(s), not approved")
    report.check("rejection names a problem", approved or bool(blocking or unmet),
                 "verdict is supported" if approved or blocking or unmet
                 else "approved=false but no blocking item or unmet requirement was given")
    return report


def tests_pass(command: str):
    """Gate factory: the given shell command must exit 0."""
    def gate(envelope: EnvelopeBase, run) -> GateReport:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        ok = result.returncode == 0
        note = f"exit {result.returncode}"
        if not ok:
            note += "\n" + (result.stdout + result.stderr)[-TAIL_CHARS:]
        return GateReport().check(command, ok, note)
    gate.__name__ = f"tests_pass({command})"
    return gate

def has_sections(*names: str):
    """Gate factory: the artifact carries these markdown headings, each with content.

    `artifacts_exist` catches an agent that claimed a file it never wrote;
    `files_non_empty` catches a file with nothing in it. Neither catches the
    common one: a document in the right SHAPE with a heading left hollow —
    "## Testing Decisions" followed by the next heading. A reader finds that
    out three steps later, which is the expensive place to find it.

    A heading present but empty FAILS. Emptiness is the whole point of the
    check; a section the agent had nothing to say about is a section it should
    have said "none, because ..." in.
    """

    def gate(envelope: EnvelopeBase, run) -> GateReport:
        report = GateReport()
        for artifact in envelope.artifacts:
            path = Path(artifact)
            if not path.exists():
                continue                   # artifacts_exist owns that failure
            text = path.read_text(encoding="utf-8", errors="replace")
            # Split on markdown headings of any level, keeping the heading text.
            blocks: dict[str, str] = {}
            current = None
            for line in text.splitlines():
                heading = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
                if heading:
                    current = heading.group(1).strip().lower()
                    blocks[current] = ""
                elif current is not None:
                    blocks[current] += line + "\n"
            for name in names:
                key = name.strip().lower()
                if key not in blocks:
                    report.check(f"{path.name} § {name}", False, "section missing")
                    continue
                body = blocks[key].strip()
                report.check(f"{path.name} § {name}", bool(body),
                             f"{len(body)} chars" if body else "section is present but empty")
        return report

    return gate


def tickets_form_a_dag(envelope: EnvelopeBase, run) -> GateReport:
    """The breakdown is actually startable, and actually finishable.

    A dependency graph is arithmetic, so code checks it — an agent re-reading
    its own list to find a cycle is an agent grading its own homework. Four
    ways a breakdown can be born dead:

      · a blocker that does not exist   → the ticket can never unblock
      · a ticket blocking itself        → same, wearing a disguise
      · a cycle                         → the frontier is empty forever
      · nothing unblocked at all        → nowhere to start

    The fifth check is ordering: numbered blockers-first, so "work the top of
    the list" is true instead of advice. It is the one a reader relies on
    without ever verifying.
    """
    report = GateReport()
    tickets = list(getattr(envelope, "tickets", []) or [])
    if not tickets:
        report.check("tickets", False, "no tickets in the envelope")
        return report

    numbers = {t.number for t in tickets}
    for ticket in tickets:
        missing = [b for b in ticket.blocked_by if b not in numbers]
        report.check(f"#{ticket.number} blockers exist", not missing,
                     f"blocked by {missing}, which do not exist" if missing else "all present")
        # The note is read as EVIDENCE, not as the check's label: a fixed note
        # makes the passing line say "blocks itself" with a ✓ in front of it, and
        # a trace that lies about what passed is worse than no trace at all.
        blocks_self = ticket.number in ticket.blocked_by
        report.check(f"#{ticket.number} does not block itself", not blocks_self,
                     "blocks itself" if blocks_self else "does not")
        later = [b for b in ticket.blocked_by if b >= ticket.number]
        report.check(f"#{ticket.number} numbered after its blockers", not later,
                     f"blocked by {later}, which come later" if later else "in order")

    # Kahn: peel off everything whose blockers are already resolved. What is
    # left when nothing peels is exactly the cycle.
    pending = {t.number: set(b for b in t.blocked_by if b in numbers) for t in tickets}
    resolved: set[int] = set()
    progress = True
    while progress:
        progress = False
        for number, blockers in list(pending.items()):
            if blockers <= resolved:
                resolved.add(number)
                pending.pop(number)
                progress = True
    report.check("no cycles", not pending,
                 f"{sorted(pending)} can never start — they depend on each other" if pending else
                 f"{len(tickets)} tickets, all reachable")

    startable = [t.number for t in tickets if not t.blocked_by]
    report.check("something can start now", bool(startable),
                 f"start at {startable}" if startable else "every ticket is blocked")
    return report
