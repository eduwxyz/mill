# 02 — Make the legacy session API reusable without changing it

**What to build:** Existing single-database visualizer users and automation continue to receive the same unprefixed health, session, live-event, envelope, gate, prompt, and archive API behavior while the session API can also be mounted independently for a supplied database resolver.

**Blocked by:** None — can start immediately.

**Status:** done

- [ ] With one supplied database, every existing unprefixed endpoint keeps its current path, request and response shape, status behavior, and archive semantics.
- [ ] The session route group can be constructed and mounted in a Bun HTTP test with a temporary Mill database without starting a production listening server.
- [ ] Invalid session or agent path segments remain rejected, missing sessions and prompt files retain their current observable outcomes, and handler failures remain contained as API errors.
- [ ] Focused Bun tests exercise the exported route group through HTTP responses and persisted archive results rather than handler internals.
