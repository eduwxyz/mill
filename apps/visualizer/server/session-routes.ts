import { resolve, sep, join } from "node:path";
import type { MillDb } from "./db.ts";
import type { AgentPrompts, ApiError, HealthResponse } from "../shared/types.ts";

const DEFAULT_LIMIT = 500;

export type DatabaseResolver = (request: Request) => MillDb | Promise<MillDb>;

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function notFound(message: string): Response {
  return json({ error: message } satisfies ApiError, 404);
}

/** Guard every handler so a malformed query can't take the server down mid-run. */
function safely(
  handler: (req: Request) => Response | Promise<Response>,
): (req: Request) => Promise<Response> {
  return async (req) => {
    try {
      return await handler(req);
    } catch (error) {
      console.error(`[mill] ${req.method} ${new URL(req.url).pathname}:`, error);
      return json({ error: (error as Error).message } satisfies ApiError, 500);
    }
  };
}

/**
 * adw_ids and agent names are path segments on disk, so anything that isn't a
 * plain identifier is rejected outright rather than sanitized into something
 * that might still escape the sessions directory.
 */
const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/;

function isSafeSegment(value: string): boolean {
  return SAFE_SEGMENT.test(value) && value !== "." && value !== "..";
}

function param(req: Request, key: string): string {
  return decodeURIComponent(
    (req as Request & { params: Record<string, string> }).params[key] ?? "",
  );
}

function intQuery(req: Request, key: string, fallback: number): number {
  const raw = new URL(req.url).searchParams.get(key);
  if (raw === null || raw.trim() === "") return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

/**
 * Build the legacy, unprefixed visualizer API routes around a database resolver.
 * The resolver is called for each request, allowing the same route group to be
 * mounted by a host that chooses a MillDb from the request context.
 */
export function createSessionRoutes(resolveDb: DatabaseResolver) {
  const dbFor = (req: Request): Promise<MillDb> => Promise.resolve(resolveDb(req));

  return {
    routes: {
      "/api/health": safely(async (req) => {
        const db = await dbFor(req);
        return json({
          ok: true,
          db: db.path,
          journal_mode: db.journalMode,
          sessions: db.sessionCount(),
        } satisfies HealthResponse);
      }),

      "/api/sessions": safely(async (req) => {
        const db = await dbFor(req);
        return json(db.sessions(intQuery(req, "limit", 200)));
      }),

      "/api/sessions/:adw_id": safely(async (req) => {
        const db = await dbFor(req);
        const adwId = param(req, "adw_id");
        const detail = db.sessionDetail(adwId);
        return detail ? json(detail) : notFound(`no session ${adwId}`);
      }),

      // The one write. Archiving is review triage — it belongs to the reader, not
      // to the run — so it never touches anything a tracer wrote.
      "/api/sessions/:adw_id/archive": {
        POST: safely(async (req) => {
          const db = await dbFor(req);
          const adwId = param(req, "adw_id");
          if (!isSafeSegment(adwId)) {
            return json({ error: "invalid adw_id" } satisfies ApiError, 400);
          }
          const body = (await req.json().catch(() => ({}))) as { archived?: unknown };
          const archived = body.archived === undefined ? true : Boolean(body.archived);
          return db.setArchived(adwId, archived)
            ? json({ adw_id: adwId, archived })
            : notFound(`no session ${adwId}`);
        }),
      },

      "/api/sessions/:adw_id/events": safely(async (req) => {
        const db = await dbFor(req);
        return json(
          db.events(
            param(req, "adw_id"),
            intQuery(req, "after", 0),
            intQuery(req, "limit", DEFAULT_LIMIT),
          ),
        );
      }),

      "/api/sessions/:adw_id/envelopes": safely(async (req) => {
        const db = await dbFor(req);
        return json(db.envelopes(param(req, "adw_id")));
      }),

      "/api/sessions/:adw_id/gates": safely(async (req) => {
        const db = await dbFor(req);
        return json(db.gates(param(req, "adw_id")));
      }),

      // The exact prompts an agent was sent, read from the session dir. Files are
      // the raw record; the db has no copy of them.
      "/api/sessions/:adw_id/agents/:agent/prompts": safely(async (req) => {
        const db = await dbFor(req);
        const adwId = param(req, "adw_id");
        const agent = param(req, "agent");
        if (!isSafeSegment(adwId) || !isSafeSegment(agent)) {
          return json({ error: "invalid adw_id or agent" } satisfies ApiError, 400);
        }
        if (!db.session(adwId)) return notFound(`no session ${adwId}`);

        const dir = resolve(db.sessionsDir, adwId, agent, "prompts");
        // Defense in depth: the segment check already forbids traversal.
        if (dir !== db.sessionsDir && !dir.startsWith(db.sessionsDir + sep)) {
          return json({ error: "invalid path" } satisfies ApiError, 400);
        }

        // A prompt file is absent whenever the agent never ran in this session —
        // a normal state, so it reads as null rather than an error.
        const read = async (name: string): Promise<string | null> => {
          const file = Bun.file(join(dir, `${name}.md`));
          return (await file.exists()) ? await file.text() : null;
        };
        return json({
          system: await read("system"),
          user: await read("user"),
        } satisfies AgentPrompts);
      }),
    },
  };
}
