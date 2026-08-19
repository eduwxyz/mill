# Ticket Breakdown Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Read the spec named in `prompt`, and read `docs/adr/` if it exists. Explore the
codebase enough to know what already exists and where the seams are.

Write ONE FILE PER TICKET into the directory named in `prompt`, named
`<NN>-<slug>.md`, numbered from `01` in dependency order. Never one combined
file.

Each file:

```markdown
# <NN> — <title>

**What to build:** the end-to-end behaviour this ticket makes work, from the
user's perspective — not a layer-by-layer implementation list.

**Blocked by:** the numbers and titles that gate this one, or
"None — can start immediately".

**Status:** ready-for-agent

- [ ] observable acceptance criterion
- [ ] observable acceptance criterion
```

Then emit your `Report` JSON.

## Report

Respond with ONLY valid JSON matching `TicketsOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: how you cut the work>",
  "tickets": [
    {
      "number": 1,
      "title": "<short descriptive name>",
      "delivers": "<the end-to-end behaviour, from the user's side>",
      "blocked_by": [],
      "acceptance": ["<observable outcome>"],
      "path": "<dir>/01-<slug>.md"
    }
  ],
  "frontier": [1],
  "prefactors": [],
  "artifacts": ["<every ticket file you wrote>"]
}
```
