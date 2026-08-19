#!/usr/bin/env python3
"""Acceptance criterion for ticket 03: scoped multi-project visualizer APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
VISUALIZER = ROOT / "apps" / "visualizer"


BUN_TEST = r'''
import { test } from "bun:test";
import { Database } from "bun:sqlite";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { pathToFileURL } from "node:url";

const visualizerDir = process.env.VISUALIZER_DIR!;
const testRoot = process.env.ACCEPTANCE_TMP!;
const resultPath = process.env.ACCEPTANCE_RESULT!;
const failures: string[] = [];

type JsonRecord = Record<string, unknown>;
type HttpResponse = {
  status: number;
  text: string;
  body: unknown;
  headers: Headers;
};
type ProjectRecord = {
  name: string;
  location: string;
  available: boolean;
  error: unknown;
  errorPresent: boolean;
};
type ProjectListing = {
  projects: Map<string, ProjectRecord>;
  defaultName: string | null;
};
type RouteConfig = {
  routes: Record<string, unknown>;
  fetch?: (request: Request) => Response | Promise<Response>;
  description: string;
};

function compact(value: unknown): string {
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value);
  } catch {
    text = String(value);
  }
  return text.replace(/\s+/g, " ").slice(0, 500) || "(empty)";
}

function fail(expected: string, found: unknown, at: string): void {
  failures.push(`expected ${expected}, found ${compact(found)}, at ${at}`);
}

function check(condition: boolean, expected: string, found: unknown, at: string): void {
  if (!condition) fail(expected, found, at);
}

function exact(actual: unknown, expected: unknown, at: string): void {
  check(isDeepStrictEqual(actual, expected), JSON.stringify(expected), actual, at);
}

function record(value: unknown): JsonRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function firstOwn(recordValue: JsonRecord, names: string[]): { found: boolean; value: unknown } {
  for (const name of names) {
    if (Object.prototype.hasOwnProperty.call(recordValue, name)) {
      return { found: true, value: recordValue[name] };
    }
  }
  return { found: false, value: undefined };
}

function errorText(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  const item = record(value);
  if (item) {
    const picked = firstOwn(item, ["error", "message", "reason", "code"]);
    if (typeof picked.value === "string") return picked.value;
  }
  return compact(value);
}

async function http(base: string, path: string, init?: RequestInit): Promise<HttpResponse> {
  const response = await fetch(`${base}${path}`, init);
  const text = await response.text();
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    body = { non_json_body: text };
  }
  return { status: response.status, text, body, headers: response.headers };
}

function assertJson(response: HttpResponse, at: string): void {
  check(
    response.headers.get("content-type") === "application/json; charset=utf-8",
    "JSON content-type application/json; charset=utf-8",
    response.headers.get("content-type"),
    at,
  );
  check(
    response.headers.get("cache-control") === "no-store",
    "cache-control no-store",
    response.headers.get("cache-control"),
    at,
  );
}

function apiError(response: HttpResponse): string | null {
  const value = record(response.body);
  return typeof value?.error === "string" && value.error.length > 0 ? value.error : null;
}

function mount(config: RouteConfig): ReturnType<typeof Bun.serve> {
  return Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    routes: config.routes,
    fetch: config.fetch ?? ((request) => {
      const path = new URL(request.url).pathname;
      return new Response(JSON.stringify({ error: `no route ${path}` }), {
        status: 404,
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }),
  });
}

function serverFiles(directory: string): string[] {
  if (!existsSync(directory)) return [];
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const file = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...serverFiles(file));
    else if (entry.isFile() && entry.name.endsWith(".ts") && entry.name !== "index.ts") files.push(file);
  }
  return files;
}

function routeConfig(value: unknown, description: string): RouteConfig | null {
  const outer = record(value);
  const routesValue = outer?.routes ?? value;
  const routes = record(routesValue);
  if (!routes || !Object.prototype.hasOwnProperty.call(routes, "/api/projects")) return null;
  const fetchValue = outer?.fetch;
  return {
    routes,
    fetch: typeof fetchValue === "function"
      ? fetchValue as (request: Request) => Response | Promise<Response>
      : undefined,
    description,
  };
}

/**
 * The ticket deliberately calls for a mountable server seam but does not name
 * it. Discover an exported seam by its observable /api/projects route rather
 * than imposing a new production API name on the implementation.
 */
async function projectRouteConfig(registry: unknown, resolution: unknown): Promise<RouteConfig | null> {
  const resolutionRecord = record(resolution) ?? {};
  const defaultProjectName = resolutionRecord.defaultProjectName;
  const projects = resolutionRecord.projects;
  const options = {
    registry,
    projectRegistry: registry,
    resolution,
    projectResolution: resolution,
    projects,
    defaultProjectName,
    defaultProject: defaultProjectName,
  };
  const calls: Array<{ label: string; args: unknown[] }> = [
    { label: "(registry, resolution)", args: [registry, resolution] },
    { label: "(registry, defaultProjectName)", args: [registry, defaultProjectName] },
    { label: "(resolution, registry)", args: [resolution, registry] },
    { label: "(options)", args: [options] },
    { label: "(registry)", args: [registry] },
    { label: "(resolution)", args: [resolution] },
    { label: "(projects, defaultProjectName)", args: [projects, defaultProjectName] },
  ];

  for (const file of serverFiles(join(visualizerDir, "server"))) {
    let module: Record<string, unknown>;
    try {
      module = await import(pathToFileURL(file).href) as Record<string, unknown>;
    } catch {
      continue;
    }
    for (const [name, exported] of Object.entries(module)) {
      if (typeof exported !== "function") continue;
      for (const call of calls) {
        try {
          const candidate = routeConfig(
            await (exported as (...args: unknown[]) => unknown)(...call.args),
            `${file.replace(`${visualizerDir}/`, "")}:${name}${call.label}`,
          );
          if (candidate) return candidate;
        } catch {
          // Exports that are not the server seam, and seams with another input
          // shape, are not evidence of a mountable project API.
        }
      }
    }
  }
  return null;
}

function makeMillDatabase(path: string, label: string): void {
  mkdirSync(dirname(path), { recursive: true });
  const db = new Database(path);
  try {
    // This is the observed Mill schema: every endpoint under test reads one of
    // these real tables, while archive writes sessions.archived.
    db.exec(`
      PRAGMA journal_mode=WAL;
      PRAGMA synchronous=NORMAL;
      CREATE TABLE sessions (
        adw_id TEXT PRIMARY KEY, adw_name TEXT, request TEXT, status TEXT,
        engineer TEXT, started_at TEXT, ended_at TEXT, total_tokens INTEGER,
        total_cost REAL, archived INTEGER DEFAULT 0
      );
      CREATE TABLE phases (
        phase_id TEXT PRIMARY KEY, adw_id TEXT, seq INTEGER, name TEXT,
        kind TEXT, owner TEXT, description TEXT, status TEXT, attempt INTEGER,
        retries INTEGER, error TEXT, started_at TEXT, ended_at TEXT
      );
      CREATE TABLE events (
        event_id TEXT PRIMARY KEY, adw_id TEXT, phase_id TEXT, parent_id TEXT,
        type TEXT, name TEXT, payload_json TEXT, tokens INTEGER,
        started_at TEXT, ended_at TEXT
      );
      CREATE TABLE envelopes (
        envelope_id TEXT PRIMARY KEY, adw_id TEXT, phase_id TEXT, agent TEXT,
        output_type TEXT, payload_json TEXT, valid INTEGER, attempt INTEGER,
        created_at TEXT
      );
      CREATE TABLE gate_results (
        id INTEGER PRIMARY KEY, adw_id TEXT, phase_id TEXT, attempt INTEGER,
        gate TEXT, passed INTEGER, violations_json TEXT, checks_json TEXT,
        created_at TEXT
      );
      CREATE TABLE agent_sessions (
        adw_id TEXT, agent TEXT, coding_agent TEXT, model TEXT, session_id TEXT,
        color TEXT, context_tokens INTEGER, context_window INTEGER,
        created_at TEXT, last_used_at TEXT, PRIMARY KEY (adw_id, agent)
      );
    `);
    db.query(`INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "collision-42", `${label}-flow`, `${label} session request`, "success", `${label}-engineer`,
      "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z", 42, 1.25, 0,
    );
    db.query(`INSERT INTO phases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "phase-42", "collision-42", 1, `${label}-build`, "code", `${label}-owner`, `${label} phase`,
      "success", 1, 0, null, "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z",
    );
    db.query(`INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "event-42", "collision-42", "phase-42", null, "tool_call", `${label}: bash`,
      JSON.stringify({ project: label }), 3, "2025-01-02T03:05:05.000Z", "2025-01-02T03:05:06.000Z",
    );
    db.query(`INSERT INTO envelopes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "envelope-42", "collision-42", "phase-42", "worker", `${label}Output`,
      JSON.stringify({ project: label }), 1, 1, "2025-01-02T03:06:05.000Z",
    );
    db.query(`INSERT INTO gate_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      1, "collision-42", "phase-42", 1, `${label}_gate`, 1, "[]",
      JSON.stringify([{ item: label, ok: true, note: `${label} present` }]), "2025-01-02T03:07:05.000Z",
    );
    db.query(`INSERT INTO agent_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "collision-42", "worker", "pi", `${label}-model`, `${label}-worker-session`, "#abcdef",
      50, 100, "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z",
    );
  } finally {
    db.close();
  }

  const prompts = join(dirname(path), "sessions", "collision-42", "worker", "prompts");
  mkdirSync(prompts, { recursive: true });
  writeFileSync(join(prompts, "system.md"), `${label} system prompt`);
  writeFileSync(join(prompts, "user.md"), `${label} user prompt`);
}

function archivedValue(path: string): number | null {
  const db = new Database(path, { readonly: true });
  try {
    return db.query<{ archived: number }, []>(
      "SELECT archived FROM sessions WHERE adw_id = 'collision-42'",
    ).get()?.archived ?? null;
  } finally {
    db.close();
  }
}

function normalizeListing(value: unknown): ProjectListing | null {
  const outer = record(value);
  const rawProjects = Array.isArray(value)
    ? value
    : Array.isArray(outer?.projects)
      ? outer.projects
      : null;
  if (!rawProjects) return null;

  const projects = new Map<string, ProjectRecord>();
  let markedDefault: string | null = null;
  for (const raw of rawProjects) {
    const item = record(raw);
    if (!item || typeof item.name !== "string") return null;
    const location = firstOwn(item, ["location", "dbPath", "databasePath", "database", "db", "path"]);
    if (typeof location.value !== "string") return null;
    const available = firstOwn(item, ["available", "availability"]);
    if (typeof available.value !== "boolean") return null;
    const reportedError = firstOwn(item, [
      "availabilityError", "availability_error", "latestAvailabilityError", "latest_error", "error", "errorMessage",
    ]);
    if (!reportedError.found) return null;
    if (item.default === true || item.isDefault === true) markedDefault = item.name;
    projects.set(item.name, {
      name: item.name,
      location: location.value,
      available: available.value,
      error: reportedError.value,
      errorPresent: reportedError.found,
    });
  }

  const defaultValue = outer ? firstOwn(outer, ["defaultProjectName", "defaultProject", "default_project", "default"]) : { found: false, value: undefined };
  const defaultName = typeof defaultValue.value === "string" ? defaultValue.value : markedDefault;
  return { projects, defaultName };
}

function isNoError(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function scoped(project: string, suffix: string): string {
  return `/api/projects/${encodeURIComponent(project)}${suffix}`;
}

function legacySuffixes(): Array<{ label: string; suffix: string; init?: RequestInit }> {
  return [
    { label: "health", suffix: "/health" },
    { label: "sessions", suffix: "/sessions" },
    { label: "session detail", suffix: "/sessions/collision-42" },
    { label: "events", suffix: "/sessions/collision-42/events?after=0&limit=1" },
    { label: "envelopes", suffix: "/sessions/collision-42/envelopes" },
    { label: "gates", suffix: "/sessions/collision-42/gates" },
    { label: "agent prompts", suffix: "/sessions/collision-42/agents/worker/prompts" },
    {
      label: "archive", suffix: "/sessions/collision-42/archive", init: {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ archived: false }),
      },
    },
  ];
}

async function compareToLegacy(
  scopedBase: string,
  project: string,
  legacyBase: string,
  at: string,
): Promise<void> {
  for (const endpoint of legacySuffixes()) {
    const actual = await http(scopedBase, scoped(project, endpoint.suffix), endpoint.init);
    const legacy = await http(legacyBase, `/api${endpoint.suffix}`, endpoint.init);
    check(actual.status === legacy.status, `legacy HTTP status ${legacy.status}`, actual.status, `${at} ${endpoint.label}`);
    check(actual.text === legacy.text, `byte-compatible legacy JSON ${legacy.text}`, actual.text, `${at} ${endpoint.label}`);
    check(
      actual.headers.get("content-type") === legacy.headers.get("content-type"),
      `legacy content-type ${legacy.headers.get("content-type")}`,
      actual.headers.get("content-type"),
      `${at} ${endpoint.label}`,
    );
    check(
      actual.headers.get("cache-control") === legacy.headers.get("cache-control"),
      `legacy cache-control ${legacy.headers.get("cache-control")}`,
      actual.headers.get("cache-control"),
      `${at} ${endpoint.label}`,
    );
  }
}

async function waitForHealthy(base: string, project: string, processHandle: ReturnType<typeof Bun.spawn>): Promise<HttpResponse | null> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await http(base, scoped(project, "/health"));
      if (response.status === 200) return response;
    } catch {
      // The process has not bound its port yet.
    }
    const exited = await Promise.race([
      processHandle.exited.then((code) => ({ exited: true, code })),
      Bun.sleep(50).then(() => ({ exited: false, code: null })),
    ]);
    if (exited.exited) return null;
  }
  return null;
}

async function unusedPort(): Promise<number> {
  const probe = Bun.serve({ hostname: "127.0.0.1", port: 0, fetch: () => new Response("probe") });
  const port = probe.port;
  probe.stop(true);
  return port;
}

async function stopWithInterrupt(processHandle: ReturnType<typeof Bun.spawn>): Promise<number | null> {
  try { processHandle.kill("SIGINT"); } catch { return null; }
  const result = await Promise.race([
    processHandle.exited.then((code) => ({ done: true, code })),
    Bun.sleep(5000).then(() => ({ done: false, code: null })),
  ]);
  if (!result.done) {
    try { processHandle.kill("SIGKILL"); } catch {}
    return null;
  }
  return result.code;
}

async function productionShutdownAndReopen(
  configFile: string,
  alphaPath: string,
  betaPath: string,
): Promise<void> {
  const start = async (): Promise<{ process: ReturnType<typeof Bun.spawn>; base: string } | null> => {
    const port = await unusedPort();
    const processHandle = Bun.spawn(
      ["bun", "run", "server/index.ts", "--projects", configFile],
      {
        cwd: visualizerDir,
        env: { ...process.env, PORT: String(port) },
        stdout: "ignore",
        stderr: "ignore",
      },
    );
    const base = `http://127.0.0.1:${port}`;
    const ready = await waitForHealthy(base, "shutdown-alpha", processHandle);
    if (!ready) {
      fail(
        "production visualizer to start and serve scoped shutdown-alpha health",
        "no HTTP 200 before process exit or startup deadline",
        "bun run server/index.ts --projects <temporary config>",
      );
      try { processHandle.kill("SIGKILL"); } catch {}
      return null;
    }
    return { process: processHandle, base };
  };

  const first = await start();
  if (!first) return;
  try {
    const beta = await http(first.base, scoped("shutdown-beta", "/health"));
    check(beta.status === 200, "HTTP 200", beta.status, "production scoped shutdown-beta health before SIGINT");

    const listingResponse = await http(first.base, "/api/projects");
    const listing = normalizeListing(listingResponse.body);
    check(listingResponse.status === 200, "HTTP 200", listingResponse.status, "production GET /api/projects");
    check(
      listing?.defaultName === "shutdown-alpha" && listing.projects.has("shutdown-alpha") && listing.projects.has("shutdown-beta"),
      "both production configured projects and default shutdown-alpha in GET /api/projects",
      listingResponse.body,
      "production GET /api/projects response",
    );
    const alphaDetail = await http(first.base, scoped("shutdown-alpha", "/sessions/collision-42"));
    const betaDetail = await http(first.base, scoped("shutdown-beta", "/sessions/collision-42"));
    check(
      (record(alphaDetail.body)?.session as JsonRecord | undefined)?.request === "shutdown-alpha session request",
      "shutdown-alpha data through the production scoped route",
      alphaDetail.body,
      "production scoped shutdown-alpha collision-42",
    );
    check(
      (record(betaDetail.body)?.session as JsonRecord | undefined)?.request === "shutdown-beta session request",
      "shutdown-beta data through the production scoped route",
      betaDetail.body,
      "production scoped shutdown-beta collision-42",
    );
    for (const project of ["shutdown-alpha", "shutdown-beta"]) {
      for (const endpoint of legacySuffixes()) {
        const response = await http(first.base, scoped(project, endpoint.suffix), endpoint.init);
        check(response.status === 200, "HTTP 200 for every scoped legacy suffix", response.status, `production ${project} scoped ${endpoint.label}`);
      }
    }
    const alphaWrite = await http(first.base, scoped("shutdown-alpha", "/sessions/collision-42/archive"), { method: "POST" });
    check(alphaWrite.status === 200, "HTTP 200 for production shutdown-alpha archive", alphaWrite.status, "production scoped shutdown-alpha archive");
    check(archivedValue(alphaPath) === 1, "archived shutdown-alpha only in its production database", archivedValue(alphaPath), "production shutdown-alpha mill.db after archive");
    check(archivedValue(betaPath) === 0, "unchanged shutdown-beta archive value", archivedValue(betaPath), "production shutdown-beta mill.db after shutdown-alpha archive");
    for (const endpoint of legacySuffixes()) {
      const response = await http(first.base, `/api${endpoint.suffix}`, endpoint.init);
      check(response.status === 404, "HTTP 404 from production multi-project server", response.status, `production unprefixed ${endpoint.label}`);
    }
  } finally {
    const code = await stopWithInterrupt(first.process);
    check(code === 0, "clean SIGINT exit code 0 after opening several projects", code, "production visualizer SIGINT");
  }

  const second = await start();
  if (!second) return;
  try {
    const beta = await http(second.base, scoped("shutdown-beta", "/health"));
    check(beta.status === 200, "HTTP 200 after a prior process interruption", beta.status, "new production process scoped shutdown-beta health");
  } finally {
    const code = await stopWithInterrupt(second.process);
    check(code === 0, "clean SIGINT exit code 0 for reopened databases", code, "second production visualizer SIGINT");
  }
}

test("scoped project server APIs isolate Mill databases and preserve the single-project boundary", async () => {
  const servers: Array<ReturnType<typeof Bun.serve>> = [];
  const databases: Array<{ close(): void }> = [];
  const registries: Array<{ close(): void }> = [];
  try {
    const projectsModule = await import(pathToFileURL(join(visualizerDir, "server", "projects.ts")).href);
    const sessionRoutesModule = await import(pathToFileURL(join(visualizerDir, "server", "session-routes.ts")).href);
    const dbModule = await import(pathToFileURL(join(visualizerDir, "server", "db.ts")).href);
    const resolveProjects = projectsModule.resolveProjects as ((argv: string[]) => unknown) | undefined;
    const ProjectRegistry = projectsModule.ProjectRegistry as (new (resolution: unknown) => { close(): void }) | undefined;
    const MillDb = dbModule.MillDb as (new (path: string) => { close(): void }) | undefined;
    const createSessionRoutes = sessionRoutesModule.createSessionRoutes as ((resolver: (request: Request) => unknown) => { routes: Record<string, unknown> }) | undefined;
    if (typeof resolveProjects !== "function" || typeof ProjectRegistry !== "function" || typeof MillDb !== "function" || typeof createSessionRoutes !== "function") {
      fail(
        "the established resolver, ProjectRegistry, MillDb, and reusable legacy route group seams",
        { resolveProjects: typeof resolveProjects, ProjectRegistry: typeof ProjectRegistry, MillDb: typeof MillDb, createSessionRoutes: typeof createSessionRoutes },
        "apps/visualizer/server",
      );
      return;
    }

    const alphaPath = join(testRoot, "alpha", "mill.db");
    const betaPath = join(testRoot, "beta", "mill.db");
    const missingPath = join(testRoot, "missing", "mill.db");
    const malformedPath = join(testRoot, "malformed", "mill.db");
    makeMillDatabase(alphaPath, "alpha");
    makeMillDatabase(betaPath, "beta");
    mkdirSync(dirname(malformedPath), { recursive: true });
    writeFileSync(malformedPath, "this is not a SQLite database", "utf8");

    const multiConfig = join(testRoot, "multi-projects.json");
    writeFileSync(multiConfig, JSON.stringify({
      default: "alpha",
      projects: [
        { name: "alpha", db: alphaPath },
        { name: "beta", db: betaPath },
        { name: "missing", db: missingPath },
        { name: "malformed", db: malformedPath },
      ],
    }), "utf8");
    const multiResolution = resolveProjects(["bun", "server/index.ts", "--projects", multiConfig]);
    const multiRegistry = new ProjectRegistry(multiResolution);
    registries.push(multiRegistry);
    const multiRoutes = await projectRouteConfig(multiRegistry, multiResolution);
    if (!multiRoutes) {
      fail(
        "an exported mountable server seam serving /api/projects and scoped project session routes",
        "no importable non-production server export returned a routes object containing /api/projects",
        "apps/visualizer/server",
      );
      return;
    }
    const multiServer = mount(multiRoutes);
    servers.push(multiServer);
    const multiBase = `http://127.0.0.1:${multiServer.port}`;

    // /api/projects must report all configured paths and the configured default
    // before it tries to open the deliberately malformed database.
    let listingResponse = await http(multiBase, "/api/projects");
    check(listingResponse.status === 200, "HTTP 200", listingResponse.status, "GET /api/projects before database opens");
    assertJson(listingResponse, "GET /api/projects before database opens");
    let listing = normalizeListing(listingResponse.body);
    if (!listing) {
      fail(
        "a project listing with projects, a default project, locations, boolean availability, and latest error fields",
        listingResponse.body,
        "GET /api/projects response",
      );
      return;
    }
    exact([...listing.projects.keys()].sort(), ["alpha", "beta", "malformed", "missing"], "GET /api/projects configured names");
    check(listing.defaultName === "alpha", "configured default project alpha", listing.defaultName, "GET /api/projects default project");
    for (const expected of [
      { name: "alpha", path: alphaPath, available: true },
      { name: "beta", path: betaPath, available: true },
      { name: "missing", path: missingPath, available: false },
      { name: "malformed", path: malformedPath, available: true },
    ]) {
      const project = listing.projects.get(expected.name);
      check(!!project, `project ${expected.name} in listing`, project ?? null, "GET /api/projects");
      check(project?.location === expected.path, `resolved database location ${expected.path}`, project?.location, `GET /api/projects ${expected.name}`);
      check(project?.available === expected.available, `file availability ${expected.available}`, project?.available, `GET /api/projects ${expected.name}`);
      check(isNoError(project?.error), "no latest open error before the project is requested", project?.error, `GET /api/projects ${expected.name} before opening databases`);
    }

    const unknown = await http(multiBase, scoped("not-configured", "/sessions"));
    check(unknown.status === 404, "HTTP 404 for an unknown project", unknown.status, "GET scoped unknown project sessions");
    assertJson(unknown, "GET scoped unknown project sessions");

    const malformedFirst = await http(multiBase, scoped("malformed", "/health"));
    check(malformedFirst.status === 503, "HTTP 503 for a configured malformed database", malformedFirst.status, "GET scoped malformed health");
    assertJson(malformedFirst, "GET scoped malformed health");
    const malformedFirstError = apiError(malformedFirst);
    check(!!malformedFirstError, "a non-empty unavailable database error", malformedFirst.body, "GET scoped malformed health response");
    const healthyAfterMalformed = await http(multiBase, scoped("alpha", "/sessions"));
    check(healthyAfterMalformed.status === 200, "healthy alpha still served after malformed project failure", healthyAfterMalformed.status, "GET scoped alpha sessions after malformed failure");

    listingResponse = await http(multiBase, "/api/projects");
    listing = normalizeListing(listingResponse.body);
    const retained = listing?.projects.get("malformed");
    check(
      typeof retained?.error === "string" && retained.error.length > 0,
      "the malformed project's retained latest availability error in GET /api/projects",
      retained?.error,
      "GET /api/projects after malformed open failure",
    );
    check(
      typeof retained?.error === "string" && !!malformedFirstError && (
        retained.error.includes(malformedFirstError) || malformedFirstError.includes(retained.error)
      ),
      "the retained error reported by the scoped 503",
      { listed: retained?.error, response: malformedFirstError },
      "malformed project 503 mapping",
    );
    const malformedRetry = await http(multiBase, scoped("malformed", "/health"));
    check(malformedRetry.status === 503, "HTTP 503 on a later malformed project request", malformedRetry.status, "GET scoped malformed health retry");
    check(
      apiError(malformedRetry) === malformedFirstError,
      "the retained unavailable error on retry",
      apiError(malformedRetry),
      "GET scoped malformed health retry response",
    );

    const missingFirst = await http(multiBase, scoped("missing", "/health"));
    check(missingFirst.status === 503, "HTTP 503 for a configured missing database", missingFirst.status, "GET scoped missing health before creation");
    const healthyAfterMissing = await http(multiBase, scoped("beta", "/sessions"));
    check(healthyAfterMissing.status === 200, "healthy beta still served after missing project failure", healthyAfterMissing.status, "GET scoped beta sessions after missing failure");
    makeMillDatabase(missingPath, "missing");
    const missingRetry = await http(multiBase, scoped("missing", "/health"));
    check(missingRetry.status === 200, "HTTP 200 after a later scoped request retries a newly created database", missingRetry.status, "GET scoped missing health after creation");

    // Compare every scoped legacy suffix against the established reusable group
    // over two different DBs carrying the identical adw_id.
    const alphaLegacyDb = new MillDb(alphaPath);
    const betaLegacyDb = new MillDb(betaPath);
    databases.push(alphaLegacyDb, betaLegacyDb);
    const alphaLegacyServer = mount({ routes: createSessionRoutes(() => alphaLegacyDb).routes, description: "legacy alpha" });
    const betaLegacyServer = mount({ routes: createSessionRoutes(() => betaLegacyDb).routes, description: "legacy beta" });
    servers.push(alphaLegacyServer, betaLegacyServer);
    await compareToLegacy(multiBase, "alpha", `http://127.0.0.1:${alphaLegacyServer.port}`, "scoped alpha");
    await compareToLegacy(multiBase, "beta", `http://127.0.0.1:${betaLegacyServer.port}`, "scoped beta");

    const archiveAlpha = await http(multiBase, scoped("alpha", "/sessions/collision-42/archive"), { method: "POST" });
    check(archiveAlpha.status === 200, "HTTP 200", archiveAlpha.status, "POST scoped alpha archive");
    exact(archiveAlpha.body, { adw_id: "collision-42", archived: true }, "POST scoped alpha archive response");
    check(archivedValue(alphaPath) === 1, "archived value 1 only in alpha database", archivedValue(alphaPath), "alpha mill.db after scoped archive");
    check(archivedValue(betaPath) === 0, "unchanged archived value 0 in beta database", archivedValue(betaPath), "beta mill.db after alpha scoped archive");
    const alphaAfterArchive = await http(multiBase, scoped("alpha", "/sessions"));
    exact(alphaAfterArchive.body, [], "GET scoped alpha sessions after alpha archive");
    const betaAfterAlphaArchive = await http(multiBase, scoped("beta", "/sessions/collision-42"));
    check(
      (record(betaAfterAlphaArchive.body)?.session as JsonRecord | undefined)?.request === "beta session request",
      "beta collision-42 detail unchanged after alpha archive",
      betaAfterAlphaArchive.body,
      "GET scoped beta collision-42 after alpha archive",
    );

    for (const endpoint of legacySuffixes()) {
      const response = await http(multiBase, `/api${endpoint.suffix}`, endpoint.init);
      check(response.status === 404, "HTTP 404 with two or more configured projects", response.status, `unprefixed ${endpoint.label} in multi-project mode`);
    }

    // A one-project configuration is the compatibility boundary: its complete
    // unprefixed surface must be byte-for-byte the reusable legacy surface.
    const singlePath = join(testRoot, "single", "mill.db");
    makeMillDatabase(singlePath, "single");
    const singleConfig = join(testRoot, "single-project.json");
    writeFileSync(singleConfig, JSON.stringify({ default: "single", projects: [{ name: "single", db: singlePath }] }), "utf8");
    const singleResolution = resolveProjects(["bun", "server/index.ts", "--projects", singleConfig]);
    const singleRegistry = new ProjectRegistry(singleResolution);
    registries.push(singleRegistry);
    const singleRoutes = await projectRouteConfig(singleRegistry, singleResolution);
    if (!singleRoutes) {
      fail("a mountable server seam for exactly one configured project", "no /api/projects route factory accepted the single-project registry", "apps/visualizer/server");
      return;
    }
    const singleServer = mount(singleRoutes);
    servers.push(singleServer);
    const singleLegacyDb = new MillDb(singlePath);
    databases.push(singleLegacyDb);
    const singleLegacyServer = mount({ routes: createSessionRoutes(() => singleLegacyDb).routes, description: "legacy single" });
    servers.push(singleLegacyServer);
    const singleBase = `http://127.0.0.1:${singleServer.port}`;
    const singleLegacyBase = `http://127.0.0.1:${singleLegacyServer.port}`;
    for (const endpoint of legacySuffixes()) {
      const actual = await http(singleBase, `/api${endpoint.suffix}`, endpoint.init);
      const legacy = await http(singleLegacyBase, `/api${endpoint.suffix}`, endpoint.init);
      check(actual.status === legacy.status, `legacy HTTP status ${legacy.status}`, actual.status, `unprefixed single-project ${endpoint.label}`);
      check(actual.text === legacy.text, `byte-compatible legacy JSON ${legacy.text}`, actual.text, `unprefixed single-project ${endpoint.label}`);
      check(actual.headers.get("content-type") === legacy.headers.get("content-type"), `legacy content-type ${legacy.headers.get("content-type")}`, actual.headers.get("content-type"), `unprefixed single-project ${endpoint.label}`);
      check(actual.headers.get("cache-control") === legacy.headers.get("cache-control"), `legacy cache-control ${legacy.headers.get("cache-control")}`, actual.headers.get("cache-control"), `unprefixed single-project ${endpoint.label}`);
    }

    const shutdownAlphaPath = join(testRoot, "shutdown-alpha", "mill.db");
    const shutdownBetaPath = join(testRoot, "shutdown-beta", "mill.db");
    makeMillDatabase(shutdownAlphaPath, "shutdown-alpha");
    makeMillDatabase(shutdownBetaPath, "shutdown-beta");
    const shutdownConfig = join(testRoot, "shutdown-projects.json");
    writeFileSync(shutdownConfig, JSON.stringify({
      default: "shutdown-alpha",
      projects: [
        { name: "shutdown-alpha", db: shutdownAlphaPath },
        { name: "shutdown-beta", db: shutdownBetaPath },
      ],
    }), "utf8");
    await productionShutdownAndReopen(shutdownConfig, shutdownAlphaPath, shutdownBetaPath);
  } catch (error) {
    fail(
      "Bun scoped multi-project HTTP criterion to complete without an exception",
      errorText(error),
      "temporary Bun test",
    );
  } finally {
    for (const server of servers.reverse()) {
      try { server.stop(true); } catch {}
    }
    for (const database of databases) {
      try { database.close(); } catch {}
    }
    for (const registry of registries) {
      try { registry.close(); } catch {}
    }
    await Bun.write(resultPath, JSON.stringify(failures));
    if (failures.length > 0) process.exitCode = 1;
  }
});
'''


def single_line(value: object) -> str:
    return " ".join(str(value).split())[:500] or "(empty)"


def main() -> int:
    try:
        if not VISUALIZER.is_dir():
            print(
                "expected visualizer project directory, found missing, "
                "at apps/visualizer"
            )
            return 1

        with tempfile.TemporaryDirectory(prefix="mill-scoped-project-api-criterion-") as temp_dir:
            temp = Path(temp_dir)
            test_path = temp / "scoped_multi_project_server_api.test.ts"
            result_path = temp / "result.json"
            test_path.write_text(BUN_TEST, encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "VISUALIZER_DIR": str(VISUALIZER),
                    "ACCEPTANCE_TMP": str(temp),
                    "ACCEPTANCE_RESULT": str(result_path),
                }
            )
            completed = subprocess.run(
                ["bun", "test", str(test_path)],
                cwd=VISUALIZER,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=55,
                check=False,
            )

            failures: list[object] = []
            if result_path.is_file():
                try:
                    parsed = json.loads(result_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, list):
                        failures = parsed
                    else:
                        failures = [
                            "expected a list of focused Bun HTTP failures, "
                            f"found {single_line(parsed)}, at temporary Bun test result"
                        ]
                except (OSError, json.JSONDecodeError) as error:
                    failures = [
                        "expected readable focused Bun test results, "
                        f"found {single_line(error)}, at temporary Bun test result"
                    ]

            if failures:
                for failure in failures:
                    text = single_line(failure)
                    if text.startswith("expected ") and ", found " in text and ", at " in text:
                        print(text)
                    else:
                        print(
                            "expected an actionable focused Bun test failure, "
                            f"found {text}, at temporary Bun test"
                        )
                return 1

            if completed.returncode != 0:
                print(
                    "expected Bun scoped multi-project HTTP test to exit 0, "
                    f"found exit {completed.returncode}, at temporary Bun test"
                )
                return 1
            return 0
    except subprocess.TimeoutExpired:
        print("expected criterion to finish within 55 seconds, found timeout, at temporary Bun test")
        return 1
    except Exception as error:  # Criterion contract: readable error, no traceback.
        print(
            "expected criterion execution without an exception, "
            f"found {single_line(error)}, at tests/acceptance/03-scoped-multi-project-server-api_test.py"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
