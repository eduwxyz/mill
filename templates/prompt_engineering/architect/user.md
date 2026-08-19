# Architecture Task

## Variables

### prompt

{{prompt}}

### previous_envelope

{{previous_envelope}}

### context_handoff_dir

{{context_handoff_dir}}

## Task

Read the research files named in `prompt` from `context_handoff_dir`. Write your
design to the output file named in `prompt`, then emit your `Report` JSON.

## Report

Respond with ONLY valid JSON matching `ArchitectOutput` — no prose before or after:

```json
{
  "status": "success",
  "summary": "<one sentence: the design you propose>",
  "design": "<the approach you propose, concretely, citing real files>",
  "agreements": ["<what both landed on — one line each, no embellishment>"],
  "divergences": [
    {
      "question": "<what they could not both be right about>",
      "position_a": "<what researcher_a argued>",
      "position_b": "<what researcher_b argued>",
      "recommendation": "<the side you take, or a third way>",
      "because": "<what KILLED the other side — evidence, measurement, consequence>"
    }
  ],
  "engineer_calls": ["<closed question that only the engineer can answer>"],
  "default_path": "<what gets built if the engineer decides nothing, and what that costs>",
  "adr_candidates": [
    {
      "decision": "<the decision, in one sentence>",
      "hard_to_reverse": "<what undoing it costs — real work, not annoyance>",
      "surprising": "<what a competent reader would expect instead>",
      "alternatives": "<the options that were genuinely viable>"
    }
  ],
  "artifacts": ["<context_handoff_dir>/<the output file named in prompt>"]
}
```
