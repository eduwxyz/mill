# 04 — Navigate and inspect one named project in the browser

**What to build:** A visualizer user can open a project, session, or phase at a project-bearing hash URL and see only that project's live data; copied links preserve project context, and changing the project never reuses the prior project's polling, trace, or card state.

**Blocked by:** 03 — Serve isolated project-scoped visualizer APIs.

**Status:** ready-for-agent

- [ ] `#/<project>/`, `#/<project>/<adw_id>`, and `#/<project>/<adw_id>/<phase_id>` load the intended sessions, trace, and phase, with all generated links percent-encoding and retaining the project segment.
- [ ] Opening `#/` redirects to the default project reported by the server, while a former session-only hash is treated as a project route rather than silently showing a session from another project.
- [ ] Session lists, session cards, traces, phase details, event tails, envelopes, gates, prompts, health reads, and archive actions all issue scoped project URLs through one client URL builder; no browser UI request uses an unprefixed session endpoint.
- [ ] Navigation and breadcrumbs show the selected project before the session and phase; when exactly one project is configured, its name is plain navigation text rather than a project selector.
- [ ] Moving from one project to another resets list, trace, timer, and card state, and sessions with the same identifier in different projects do not reuse visual or local component state.
- [ ] The visualizer continues to pass its typecheck and production build after project context is propagated through every project-bound view and mutation.
