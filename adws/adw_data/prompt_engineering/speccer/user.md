# Spec Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Read the design named in `prompt` from `context_handoff_dir`, and read
`docs/adr/` if it exists. Write the spec to the path named in `prompt`, then
emit your `Report` JSON.

Use exactly these seven headings, in this order:

```markdown
## Problem Statement
The problem, from the user's perspective. Not the solution.

## Solution
The solution, from the user's perspective.

## User Stories
A long numbered list. `As a <actor>, I want <feature>, so that <benefit>`.

## Implementation Decisions
Modules and interfaces to build or change, contracts, schema shapes,
architectural calls. No file paths.

## Testing Decisions
Which seams get tested and why those; what makes a good test here
(external behaviour, never internals); prior art in this codebase.

## Out of Scope
What this deliberately does NOT do, and what would have to be true to change that.

## Further Notes
Anything unresolved, and any conflict with an existing ADR.
```

## Report

Respond with ONLY valid JSON matching `SpecOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: what this spec asks for>",
  "spec_path": "<the path from prompt>",
  "seams": ["<the test seam you chose, and why that one>"],
  "open_questions": ["<what was not decided — empty list if nothing>"],
  "artifacts": ["<the path from prompt>"]
}
```
