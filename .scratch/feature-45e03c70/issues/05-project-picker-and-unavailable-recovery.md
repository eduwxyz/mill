# 05 — Switch projects and recover unavailable ones from the picker

**What to build:** Users of a multi-project visualizer can choose a named project from the same URL, see which configured databases are currently available, and retry a project that becomes available without restarting the server.

**Blocked by:** 04 — Navigate and inspect one named project in the browser.

**Status:** ready-for-agent

- [ ] When more than one project is configured, the top bar offers a project picker whose entries show project names and current availability; opening it refreshes the project list without background availability polling.
- [ ] Selecting an available project changes to that project's root hash route and displays its sessions without retaining the previously selected project's view state.
- [ ] Selecting a temporarily unavailable project makes a scoped request, presents the unavailable outcome distinctly from an unknown project, and refreshes the picker after its 503 response so a database created later can be selected successfully in the same server session.
- [ ] An unknown project route, including a legacy session-only hash, presents a clear unknown-project outcome with access to the picker rather than displaying unrelated session data.
- [ ] With exactly one configured project, no picker control is rendered and the visualizer retains the single-project navigation appearance.
