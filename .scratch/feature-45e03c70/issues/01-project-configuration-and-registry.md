# 01 — Resolve configured projects and their database availability

**What to build:** Visualizer users can describe one or more local projects in a JSON configuration and get deterministic project names, database locations, and a default project, while existing `--db`/`MILL_DB` single-project invocation keeps its current resolution behavior when no project configuration is selected. A configured database that does not exist yet remains visible as temporarily unavailable and can become usable later without rebuilding the configured project set.

**Blocked by:** None — can start immediately.

**Status:** failed

- [ ] A JSON configuration accepts unique URL-safe project names and exactly one `db` or `repo` location per project; repository locations resolve to the standard Mill database location, `~` expands, configuration-relative paths resolve from the configuration file, and an explicit default (or the first project) is selected deterministically.
- [ ] `--projects` takes precedence over `MILL_PROJECTS_CONFIG`; with neither present, resolving the sole legacy project preserves the current `--db`, `MILL_DB`, and working-directory precedence and resolved database path.
- [ ] Malformed JSON, an empty project list, unsafe or duplicate names, an invalid default, and entries with both or neither location are rejected with an actionable configuration error rather than producing an ambiguous project set.
- [ ] A registry lists configured names, resolved database locations, and file-based availability without opening databases; requesting an unknown name is distinguishable from requesting an unavailable configured database, and a later request can open a database created after an earlier failure.
- [ ] The visualizer documents the JSON shape and project-selection invocation, and focused Bun tests cover configuration precedence, path interpretation, validation, legacy fallback, and retryable unavailable projects.
