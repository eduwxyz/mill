# Shape Review Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

The `previous_envelope` carries the whole feature's diff and the path to the
file holding it. Read the complete diff, and read in the repository the files it
touches most — the diff shows what changed, not what the thing became.

If there is a spec and tickets in `.scratch/`, read them: they say what each
piece was trying to do, and the distance between intent and result is where the
findings live.

Write the report to the path named in `prompt`, then emit your `Report` JSON.

## Report

Respond with ONLY valid JSON matching `ShapeOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: the state of the feature seen as a whole>",
  "report_path": "<the path from prompt>",
  "verdict": "<one honest sentence — including 'it is solid', if it is>",
  "what_held_up": ["<what held up across the N tickets, and why that matters>"],
  "findings": [
    {
      "what": "<what is crooked, in one sentence>",
      "where": ["server.ts:120-180", "public/index.html:44"],
      "why_it_matters": "<what it costs three months from now, concretely>",
      "severity": "high",
      "suggested_ticket": "<the 'What to build' of a ticket, in observable behaviour>"
    }
  ],
  "artifacts": ["<o caminho do prompt>"]
}
```
