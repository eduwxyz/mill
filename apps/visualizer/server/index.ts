/**
 * MILL visualizer server — JSON API over a target repo's mill.db, plus the
 * built UI when ./dist exists. Reads are read-only; the single write is
 * POST /api/sessions/:adw_id/archive, which sets one review flag on a row.
 *
 * There is no ingest endpoint and no websocket. The data path is
 * agents → sqlite → web ui, and the UI gets there by polling.
 *
 *   bun run server/index.ts
 *   bun run server/index.ts --db /path/to/repo/adws/adw_data/mill.db
 *   bun run server/index.ts --projects /path/to/projects.json
 *   MILL_DB=/path/to/mill.db PORT=4600 bun run server/index.ts
 */
import { existsSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { createSessionRoutes } from "./session-routes.ts";
import { ProjectRegistry, resolveProjects } from "./projects.ts";

const PORT = Number(process.env.PORT ?? 4600);
const DIST_DIR = resolve(import.meta.dir, "..", "dist");
const projectResolution = resolveProjects();
const projectRegistry = new ProjectRegistry(projectResolution);
const configSelected = Bun.argv.includes("--projects") ||
  Bun.argv.some((arg) => arg.startsWith("--projects=")) ||
  process.env.MILL_PROJECTS_CONFIG !== undefined;

// Preserve the legacy startup failure for a single missing database. A
// configured set is different: its unavailable entries remain visible and are
// opened lazily when requested.
if (!configSelected) {
  try {
    projectRegistry.get(projectResolution.defaultProjectName);
  } catch (error) {
    console.error(`[mill] ${(error as Error).message}`);
    process.exit(1);
  }
}

function selectedProject(req: Request): string {
  return new URL(req.url).searchParams.get("project") ?? projectResolution.defaultProjectName;
}


function notFound(message: string): Response {
  return new Response(JSON.stringify({ error: message }), {
    status: 404,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

/** Serve the built SPA if it has been built; otherwise point at the dev server. */
async function serveStatic(req: Request): Promise<Response> {
  const { pathname } = new URL(req.url);

  if (!existsSync(DIST_DIR)) {
    return new Response(
      `MILL visualizer API is running on :${PORT}.\n\n` +
        `No ./dist build found. Run "bun run dev" for the Vite dev server ` +
        `(it proxies /api here), or "bun run build" to serve the UI from this process.\n`,
      { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  }

  // Reject traversal before touching the filesystem.
  const candidate = resolve(join(DIST_DIR, pathname));
  if (candidate === DIST_DIR || candidate.startsWith(DIST_DIR + "/")) {
    if (existsSync(candidate) && statSync(candidate).isFile()) {
      return new Response(Bun.file(candidate));
    }
  }

  // SPA fallback: breadcrumb routes are client-side.
  const indexHtml = join(DIST_DIR, "index.html");
  if (existsSync(indexHtml)) {
    return new Response(Bun.file(indexHtml), {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  }
  return notFound("not found");
}

const server = Bun.serve({
  port: PORT,
  routes: {
    "/api/projects": () => new Response(JSON.stringify(projectRegistry.list()), {
      headers: {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      },
    }),
    ...createSessionRoutes((req) => projectRegistry.get(selectedProject(req))).routes,
  },

  fetch(req) {
    const { pathname } = new URL(req.url);
    if (pathname.startsWith("/api/")) {
      return new Response(JSON.stringify({ error: `no route ${pathname}` }), {
        status: 404,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }
    return serveStatic(req);
  },
});

console.log(`[mill] visualizer api  http://localhost:${server.port}`);
const selected = projectResolution.projects.find(
  (project) => project.name === projectResolution.defaultProjectName,
);
console.log(`[mill] projects        ${projectResolution.projects.map((project) => project.name).join(", ")}`);
console.log(`[mill] default project  ${projectResolution.defaultProjectName} (${selected?.location})`);
console.log(
  existsSync(DIST_DIR)
    ? `[mill] serving ui from  ${DIST_DIR}`
    : `[mill] no ./dist — use "bun run dev" for the Vite dev server on :4601`,
);

process.on("SIGINT", () => {
  projectRegistry.close();
  process.exit(0);
});
