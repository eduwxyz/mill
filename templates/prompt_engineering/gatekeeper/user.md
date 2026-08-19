# Acceptance Criterion Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Read the ticket in `prompt`. Explore the repository enough to know the
language, the test tooling and what already exists.

And **go and find the data the ticket mentions.** If it talks about files,
formats or sources that already exist — here or on this machine — open at least
one before writing any check about them.

Write ONE criterion file at the path named in `prompt`. It must fail right now —
the behaviour has not been built. Then emit your `Report` JSON.

Do not implement anything. Do not modify any file other than your criterion.

## Report

Respond with ONLY valid JSON matching `CriterionOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: what this criterion proves>",
  "script_path": "<the path from prompt>",
  "command": ["<argv>", "<to>", "<run it>"],
  "covers": ["<the ticket checkbox this check makes executable>"],
  "uncovered": ["<a checkbox you could not make executable, and why>"],
  "grounded_in": ["<a REAL file/source you opened and used to write the checks>"],
  "artifacts": ["<the path from prompt>"]
}
```
