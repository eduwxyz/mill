"""The frontier: which tickets can start now, and what is already complete.

The blocking graph is arithmetic over files, so this is code — the same reason
`tickets_form_a_dag` is a gate and not an agent's opinion.

STATE LIVES IN THE TICKET FILE, on the `Status:` line. The alternative would be a
separate JSON, and it has an unpleasant failure mode: the index and the tickets
diverge, and nothing warns you. Here you open the ticket and see where it stands —
and `git log` tells the story of when it changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

READY = "ready-for-agent"
DONE = "done"
FAILED = "failed"

_NUMBER = re.compile(r"^(\d+)")
# `[^\S\n]*` and not `\s*`: `\s` includes the newline, and with re.M the `$`
# would match further along — the substitution swallowed the following blank line
# and glued the document together on every marking. A test caught it on the first
# round.
_STATUS = re.compile(r"^\*\*Status:\*\*[^\S\n]*(.+?)[^\S\n]*$", re.M)
# "**Blocked by:** 01 — title; 03 — another."  or  "None — can start immediately."
_BLOCKED = re.compile(r"^\*\*Blocked by:\*\*[^\S\n]*(.+?)[^\S\n]*$", re.M)


@dataclass
class Ticket:
    number: int
    path: Path
    status: str
    blocked_by: list[int] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.status.lower().startswith(DONE)


def _blockers(text: str) -> list[int]:
    found = _BLOCKED.search(text)
    if not found:
        return []
    body = found.group(1)
    if body.lower().startswith("none"):
        return []
    # The numbers are the contract; the titles beside them are for humans and change.
    return sorted({int(n) for n in re.findall(r"\b(\d{1,3})\b", body.split("—")[0] + body)})


def load(tickets_dir: str | Path) -> list[Ticket]:
    """Every `NN-*.md` in the directory, in numeric order."""
    directory = Path(tickets_dir)
    tickets: list[Ticket] = []
    for path in sorted(directory.glob("*.md")):
        number = _NUMBER.match(path.name)
        if not number:
            continue                      # README, notes, anything without a number
        text = path.read_text(encoding="utf-8")
        status = (_STATUS.search(text).group(1) if _STATUS.search(text) else READY)
        blocked = [b for b in _blockers(text) if b != int(number.group(1))]
        tickets.append(Ticket(int(number.group(1)), path, status, blocked))
    return tickets


def frontier(tickets: list[Ticket]) -> list[Ticket]:
    """The ones that can start NOW: not complete, and all their blockers are.

    A blocker that failed does not count as complete — that is what stops the loop
    from building on top of a defect while the engineer is not looking.
    """
    done = {t.number for t in tickets if t.done}
    return [t for t in tickets
            if not t.done and t.status.lower() != FAILED and set(t.blocked_by) <= done]


def mark(ticket: Ticket, status: str) -> None:
    """Rewrites the `Status:` line in place, preserving the rest of the file."""
    text = ticket.path.read_text(encoding="utf-8")
    updated, count = _STATUS.subn(f"**Status:** {status}", text, count=1)
    if count == 0:
        # A ticket without the line (hand-written?) — append it after "Blocked by".
        updated = text.rstrip() + f"\n\n**Status:** {status}\n"
    ticket.path.write_text(updated, encoding="utf-8")
    ticket.status = status
