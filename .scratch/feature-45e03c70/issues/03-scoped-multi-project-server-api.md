# 03 — Serve isolated project-scoped visualizer APIs

**What to build:** A single visualizer process serves every configured project through named API paths, lets callers discover project availability and the default project, and prevents a request for one project's session from reading or archiving another project's database.

**Blocked by:** 01 — Resolve configured projects and their database availability; 02 — Make the legacy session API reusable without changing it.

**Status:** done

- [ ] `GET /api/projects` returns every configured project's name, resolved database location, availability, latest availability error, and the configured default project without opening each database.
- [ ] Each existing session endpoint is available below `/api/projects/:project/` with its current suffix and operates only on that project's database; an unknown project returns 404 and a known database that cannot open returns 503 with its retained error.
- [ ] Two configured databases containing the same session identifier remain isolated: archiving through one scoped project removes only that database's session and leaves the other project's session unchanged.
- [ ] Exactly one configured project retains the byte-compatible unprefixed API routes, while two or more configured projects expose no unprefixed session routes so an unscoped archive cannot select a default database.
- [ ] A configured missing or malformed database does not stop healthy projects from being served, later scoped requests retry it, and interrupting the server after opening several projects terminates cleanly so a new process can reopen their databases.
- [ ] Bun HTTP tests mount the server seam with temporary Mill databases and prove scoped isolation, 404 versus 503 mapping, project listing, and the single-versus-multiple unprefixed-route safety boundary.
