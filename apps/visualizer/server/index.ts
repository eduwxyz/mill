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
 *   MILL_DB=/path/to/mill.db PORT=4600 bun run server/index.ts
 */
import { existsSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { MillDb, resolveDbPath } from "./db.ts";
import { createSessionRoutes } from "./session-routes.ts";

const PORT = Number(process.env.PORT ?? 4600);
const DIST_DIR = resolve(import.meta.dir, "..", "dist");

const dbPath = resolveDbPath();
let db: MillDb;
try {
  db = new MillDb(dbPath);
} catch (error) {
  console.error(`[mill] ${(error as Error).message}`);
  process.exit(1);
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
  routes: createSessionRoutes(() => db).routes,

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
console.log(`[mill] db              ${db.path}  [journal_mode=${db.journalMode}]`);
console.log(
  existsSync(DIST_DIR)
    ? `[mill] serving ui from  ${DIST_DIR}`
    : `[mill] no ./dist — use "bun run dev" for the Vite dev server on :4601`,
);

process.on("SIGINT", () => {
  db.close();
  process.exit(0);
});
