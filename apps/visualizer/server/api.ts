import { ProjectRegistry, type ProjectResolution } from "./projects.ts";
import { createSessionRoutes } from "./session-routes.ts";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function projectParam(request: Request): string {
  const params = (request as Request & { params?: Record<string, string> }).params;
  return decodeURIComponent(params?.project ?? "");
}

type SessionRoutes = ReturnType<typeof createSessionRoutes>["routes"];
type SessionRoute = SessionRoutes[keyof SessionRoutes];

type ProjectRoutes = {
  routes: Record<string, SessionRoute | (() => Response)>;
};

function scopedRoutes(
  routes: SessionRoutes,
): Record<string, SessionRoute> {
  const result: Record<string, SessionRoute> = {};
  for (const [path, handler] of Object.entries(routes)) {
    result[`/api/projects/:project${path.slice("/api".length)}`] = handler;
  }
  return result;
}

/**
 * Build the complete project-aware API without opening any database. The
 * legacy route group is reused verbatim; only its URL prefix and database
 * resolver change for scoped requests.
 */
export function createProjectRoutes(
  registry: ProjectRegistry,
  resolution: ProjectResolution,
): ProjectRoutes {
  const routes: Record<string, SessionRoute | (() => Response)> = {
    "/api/projects": () => json({
      projects: registry.list(),
      defaultProjectName: resolution.defaultProjectName,
    }),
    ...scopedRoutes(
      createSessionRoutes((request) => registry.get(projectParam(request))).routes,
    ),
  };

  // Preserve the old API only when there is exactly one configured project.
  // With multiple projects, an unscoped write must not silently choose one.
  if (resolution.projects.length === 1) {
    Object.assign(
      routes,
      createSessionRoutes(() => registry.get(resolution.defaultProjectName)).routes,
    );
  }

  return { routes };
}
