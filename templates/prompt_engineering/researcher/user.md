# Research Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Study this repository, then write your approach to the file named in `prompt`,
inside `context_handoff_dir`. Then emit your `Report` JSON.

Keep `approach` concrete enough that a builder could start from it: real file
paths, real module names, the shape of the first slice.

`rejected` is not optional. If you cannot name an alternative you considered
and what killed it, you have not explored — you have picked the first idea.

## Report

Respond with ONLY valid JSON matching `ResearchOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: the approach you landed on>",
  "approach": "<what you would do, concretely, in THIS repo — cite files you read>",
  "rejected": "<the alternative you considered, and what killed it>",
  "risks": ["<where this breaks — be specific; 'might get slow' is not a risk>"],
  "out_of_scope": ["<what you deliberately would NOT do now>"],
  "engineer_questions": ["<what depends on business, taste or priority — reading code cannot settle these>"],
  "artifacts": ["<context_handoff_dir>/<the file named in prompt>"]
}
```
