#!/usr/bin/env python3
"""Acceptance criterion for ticket 02: reusable legacy session route group."""

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
import { isDeepStrictEqual } from "node:util";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const visualizerDir = process.env.VISUALIZER_DIR!;
const testRoot = process.env.ACCEPTANCE_TMP!;
const resultPath = process.env.ACCEPTANCE_RESULT!;
const failures: string[] = [];

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

async function http(
  base: string,
  path: string,
  init?: RequestInit,
): Promise<{ status: number; headers: Headers; body: unknown }> {
  const response = await fetch(`${base}${path}`, init);
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    body = { non_json_body: text };
  }
  return { status: response.status, headers: response.headers, body };
}

function assertJson(response: { status: number; headers: Headers; body: unknown }, at: string): void {
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

function makeFixture(dbPath: string): void {
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new Database(dbPath);
  try {
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
      "session-01", "fixture-flow", "inspect fixture", "success", "tester",
      "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z", 42, 1.25, 0,
    );
    // A pre-archived row anchors the legacy distinction: health counts every
    // session, while the review list omits archived sessions.
    db.query(`INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "hidden-02", "fixture-flow", "already reviewed", "fail", "tester",
      "2025-01-01T03:04:05.000Z", null, 7, 0.5, 1,
    );
    db.query(`INSERT INTO phases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "phase-01", "session-01", 1, "build", "code", "builder", "fixture phase",
      "success", 1, 0, null, "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z",
    );
    db.query(`INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "event-01", "session-01", "phase-01", null, "tool_call", "bash: true",
      '{"tool":"bash"}', 3, "2025-01-02T03:05:05.000Z", "2025-01-02T03:05:06.000Z",
    );
    db.query(`INSERT INTO envelopes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "envelope-01", "session-01", "phase-01", "worker", "FixtureOutput",
      '{"ok":true}', 1, 1, "2025-01-02T03:06:05.000Z",
    );
    db.query(`INSERT INTO gate_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      1, "session-01", "phase-01", 1, "fixture_gate", 1, "[]",
      '[{"item":"fixture","ok":true,"note":"present"}]', "2025-01-02T03:07:05.000Z",
    );
    db.query(`INSERT INTO agent_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`).run(
      "session-01", "worker", "pi", "fixture-model", "worker-session", "#abcdef",
      50, 100, "2025-01-02T03:04:05.000Z", "2025-01-02T03:14:05.000Z",
    );
  } finally {
    db.close();
  }

  const promptsDir = join(dirname(dbPath), "sessions", "session-01", "worker", "prompts");
  mkdirSync(promptsDir, { recursive: true });
  writeFileSync(join(promptsDir, "system.md"), "fixture system prompt");
  writeFileSync(join(promptsDir, "user.md"), "fixture user prompt");
}

function serverFiles(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...serverFiles(path));
    else if (entry.isFile() && entry.name.endsWith(".ts") && entry.name !== "index.ts") found.push(path);
  }
  return found;
}

async function findRouteFactory(db: unknown): Promise<
  | { factory: (resolver: (request: Request) => unknown) => unknown; name: string; routes: Record<string, unknown> }
  | null
> {
  const serverDir = join(visualizerDir, "server");
  if (!existsSync(serverDir)) return null;
  const required = [
    "/api/health",
    "/api/sessions",
    "/api/sessions/:adw_id",
    "/api/sessions/:adw_id/archive",
    "/api/sessions/:adw_id/events",
    "/api/sessions/:adw_id/envelopes",
    "/api/sessions/:adw_id/gates",
    "/api/sessions/:adw_id/agents/:agent/prompts",
  ];

  for (const file of serverFiles(serverDir)) {
    let module: Record<string, unknown>;
    try {
      module = await import(pathToFileURL(file).href) as Record<string, unknown>;
    } catch {
      continue;
    }
    for (const [name, exported] of Object.entries(module)) {
      if (typeof exported !== "function") continue;
      try {
        const group = await exported((_: Request) => db);
        const routes = (group as { routes?: unknown })?.routes ?? group;
        if (
          routes &&
          typeof routes === "object" &&
          required.every((path) => Object.prototype.hasOwnProperty.call(routes, path))
        ) {
          return {
            factory: exported as (resolver: (request: Request) => unknown) => unknown,
            name: `${file.replace(`${visualizerDir}/`, "")}:${name}`,
            routes: routes as Record<string, unknown>,
          };
        }
      } catch {
        // Other exported helpers (and factories with a different purpose) are
        // not the route group being sought.
      }
    }
  }
  return null;
}

async function routesFor(
  factory: (resolver: (request: Request) => unknown) => unknown,
  resolver: (request: Request) => unknown,
): Promise<Record<string, unknown>> {
  const group = await factory(resolver);
  const routes = (group as { routes?: unknown })?.routes ?? group;
  if (!routes || typeof routes !== "object") {
    throw new Error("route factory did not return a Bun routes object");
  }
  return routes as Record<string, unknown>;
}

function mount(routes: Record<string, unknown>) {
  return Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    routes,
    fetch(req) {
      return new Response(JSON.stringify({ error: `no route ${new URL(req.url).pathname}` }), {
        status: 404,
        headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
      });
    },
  });
}

test("exported session route group preserves legacy API over HTTP", async () => {
  let fixtureDb: { close(): void } | null = null;
  let server: ReturnType<typeof Bun.serve> | null = null;
  let brokenServer: ReturnType<typeof Bun.serve> | null = null;

  try {
    const dbModule = await import(pathToFileURL(join(visualizerDir, "server", "db.ts")).href);
    const MillDb = dbModule.MillDb as new (path: string) => { path: string; close(): void };
    if (typeof MillDb !== "function") {
      fail("the existing MillDb constructor", typeof MillDb, "apps/visualizer/server/db.ts");
      return;
    }

    const dbPath = join(testRoot, "data", "mill.db");
    makeFixture(dbPath);
    fixtureDb = new MillDb(dbPath);
    const factory = await findRouteFactory(fixtureDb);
    if (!factory) {
      fail(
        "an exported reusable session route group accepting a database resolver",
        "no mountable route factory outside server/index.ts",
        "apps/visualizer/server",
      );
      return;
    }

    server = mount(factory.routes);
    const base = `http://127.0.0.1:${server.port}`;

    const phase = {
      phase_id: "phase-01", adw_id: "session-01", seq: 1, name: "build", kind: "code",
      owner: "builder", description: "fixture phase", status: "success", attempt: 1,
      retries: 0, error: null, started_at: "2025-01-02T03:04:05.000Z",
      ended_at: "2025-01-02T03:14:05.000Z",
    };
    const agent = {
      adw_id: "session-01", agent: "worker", coding_agent: "pi", model: "fixture-model",
      session_id: "worker-session", color: "#abcdef", context_tokens: 50, context_window: 100,
      created_at: "2025-01-02T03:04:05.000Z", last_used_at: "2025-01-02T03:14:05.000Z",
    };
    const session = {
      adw_id: "session-01", adw_name: "fixture-flow", request: "inspect fixture", status: "success",
      engineer: "tester", started_at: "2025-01-02T03:04:05.000Z",
      ended_at: "2025-01-02T03:14:05.000Z", total_tokens: 42, total_cost: 1.25,
    };

    let response = await http(base, "/api/health");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/health");
    assertJson(response, "GET /api/health");
    exact(response.body, { ok: true, db: dbPath, journal_mode: "wal", sessions: 2 }, "GET /api/health response");

    response = await http(base, "/api/sessions");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/sessions");
    assertJson(response, "GET /api/sessions");
    exact(response.body, [{ ...session, archived: 0, phases: [phase], phase_count: 1, agents: [agent] }], "GET /api/sessions response");

    response = await http(base, "/api/sessions/session-01");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/sessions/session-01");
    assertJson(response, "GET /api/sessions/session-01");
    exact(response.body, { session, usage: { read: 0, written: 0 }, phases: [phase], agents: [agent] }, "GET /api/sessions/session-01 response");

    response = await http(base, "/api/sessions/session-01/events?after=0&limit=1");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/sessions/session-01/events");
    assertJson(response, "GET /api/sessions/session-01/events");
    exact(response.body, {
      events: [{ rowid: 1, event_id: "event-01", adw_id: "session-01", phase_id: "phase-01", parent_id: null,
        type: "tool_call", name: "bash: true", payload_json: '{"tool":"bash"}', tokens: 3,
        started_at: "2025-01-02T03:05:05.000Z", ended_at: "2025-01-02T03:05:06.000Z" }],
      cursor: 1, has_more: true,
    }, "GET /api/sessions/session-01/events response");

    response = await http(base, "/api/sessions/session-01/envelopes");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/sessions/session-01/envelopes");
    assertJson(response, "GET /api/sessions/session-01/envelopes");
    exact(response.body, [{ envelope_id: "envelope-01", adw_id: "session-01", phase_id: "phase-01", agent: "worker",
      output_type: "FixtureOutput", payload_json: '{"ok":true}', valid: 1, attempt: 1,
      created_at: "2025-01-02T03:06:05.000Z" }], "GET /api/sessions/session-01/envelopes response");

    response = await http(base, "/api/sessions/session-01/gates");
    check(response.status === 200, "HTTP 200", response.status, "GET /api/sessions/session-01/gates");
    assertJson(response, "GET /api/sessions/session-01/gates");
    exact(response.body, [{ id: 1, adw_id: "session-01", phase_id: "phase-01", attempt: 1, gate: "fixture_gate",
      passed: 1, violations_json: "[]", checks_json: '[{"item":"fixture","ok":true,"note":"present"}]',
      created_at: "2025-01-02T03:07:05.000Z" }], "GET /api/sessions/session-01/gates response");

    response = await http(base, "/api/sessions/session-01/agents/worker/prompts");
    check(response.status === 200, "HTTP 200", response.status, "GET existing agent prompts");
    assertJson(response, "GET existing agent prompts");
    exact(response.body, { system: "fixture system prompt", user: "fixture user prompt" }, "GET existing agent prompts response");

    response = await http(base, "/api/sessions/session-01/agents/absent-agent/prompts");
    check(response.status === 200, "HTTP 200", response.status, "GET absent prompt files");
    assertJson(response, "GET absent prompt files");
    exact(response.body, { system: null, user: null }, "GET absent prompt files response");

    response = await http(base, "/api/sessions/missing-session");
    check(response.status === 404, "HTTP 404", response.status, "GET missing session");
    exact(response.body, { error: "no session missing-session" }, "GET missing session response");

    response = await http(base, "/api/sessions/missing-session/events?after=7");
    check(response.status === 200, "HTTP 200", response.status, "GET missing session events");
    exact(response.body, { events: [], cursor: 7, has_more: false }, "GET missing session events response");

    response = await http(base, "/api/sessions/missing-session/envelopes");
    check(response.status === 200, "HTTP 200", response.status, "GET missing session envelopes");
    exact(response.body, [], "GET missing session envelopes response");

    response = await http(base, "/api/sessions/missing-session/gates");
    check(response.status === 200, "HTTP 200", response.status, "GET missing session gates");
    exact(response.body, [], "GET missing session gates response");

    response = await http(base, "/api/sessions/missing-session/agents/worker/prompts");
    check(response.status === 404, "HTTP 404", response.status, "GET prompts for missing session");
    exact(response.body, { error: "no session missing-session" }, "GET prompts for missing session response");

    response = await http(base, "/api/sessions/bad%2Fid/archive", { method: "POST" });
    check(response.status === 400, "HTTP 400", response.status, "POST archive with invalid session segment");
    exact(response.body, { error: "invalid adw_id" }, "POST archive with invalid session segment response");

    response = await http(base, "/api/sessions/bad%2Fid/agents/worker/prompts");
    check(response.status === 400, "HTTP 400", response.status, "GET prompts with invalid session segment");
    exact(response.body, { error: "invalid adw_id or agent" }, "GET prompts with invalid session segment response");

    response = await http(base, "/api/sessions/session-01/agents/bad%2Fagent/prompts");
    check(response.status === 400, "HTTP 400", response.status, "GET prompts with invalid agent segment");
    exact(response.body, { error: "invalid adw_id or agent" }, "GET prompts with invalid agent segment response");

    response = await http(base, "/api/sessions/missing-session/archive", { method: "POST" });
    check(response.status === 404, "HTTP 404", response.status, "POST archive missing session");
    exact(response.body, { error: "no session missing-session" }, "POST archive missing session response");

    response = await http(base, "/api/sessions/session-01/archive", { method: "POST" });
    check(response.status === 200, "HTTP 200", response.status, "POST archive default body");
    assertJson(response, "POST archive default body");
    exact(response.body, { adw_id: "session-01", archived: true }, "POST archive default body response");
    const archivedReader = new Database(dbPath, { readonly: true });
    try {
      const archived = archivedReader.query<{ archived: number }, []>(
        "SELECT archived FROM sessions WHERE adw_id = 'session-01'",
      ).get()?.archived;
      check(archived === 1, "persisted archived value 1", archived, "mill.db after POST archive");
    } finally {
      archivedReader.close();
    }
    response = await http(base, "/api/sessions");
    exact(response.body, [], "GET /api/sessions after archive");

    response = await http(base, "/api/sessions/session-01/archive", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ archived: false }),
    });
    check(response.status === 200, "HTTP 200", response.status, "POST archive restore");
    exact(response.body, { adw_id: "session-01", archived: false }, "POST archive restore response");
    const restoredReader = new Database(dbPath, { readonly: true });
    try {
      const archived = restoredReader.query<{ archived: number }, []>(
        "SELECT archived FROM sessions WHERE adw_id = 'session-01'",
      ).get()?.archived;
      check(archived === 0, "persisted archived value 0", archived, "mill.db after POST archive restore");
    } finally {
      restoredReader.close();
    }

    // A resolver failure happens while a route handler is serving a request.
    // It must become a JSON API error rather than crash the test server.
    brokenServer = mount(await routesFor(factory.factory, (_: Request) => {
      throw new Error("fixture resolver failure");
    }));
    const broken = await http(`http://127.0.0.1:${brokenServer.port}`, "/api/health");
    check(broken.status === 500, "HTTP 500 JSON API error", broken.status, "GET /api/health with handler failure");
    assertJson(broken, "GET /api/health with handler failure");
    check(
      typeof (broken.body as { error?: unknown })?.error === "string" &&
        String((broken.body as { error?: unknown }).error).length > 0,
      "a non-empty API error body",
      broken.body,
      "GET /api/health with handler failure response",
    );
  } catch (error) {
    fail("Bun HTTP route-group test to complete without an exception", error instanceof Error ? error.message : String(error), "temporary Bun test");
  } finally {
    try { brokenServer?.stop(true); } catch {}
    try { server?.stop(true); } catch {}
    try { fixtureDb?.close(); } catch {}
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

        with tempfile.TemporaryDirectory(prefix="mill-session-route-criterion-") as temp_dir:
            temp = Path(temp_dir)
            test_path = temp / "session_route_group.test.ts"
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
                timeout=45,
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
                            "expected a list of Bun HTTP test failures, "
                            f"found {single_line(parsed)}, at temporary Bun test result"
                        ]
                except (OSError, json.JSONDecodeError) as error:
                    failures = [
                        "expected readable Bun HTTP test results, "
                        f"found {single_line(error)}, at temporary Bun test result"
                    ]

            if failures:
                for failure in failures:
                    text = single_line(failure)
                    if text.startswith("expected ") and ", found " in text and ", at " in text:
                        print(text)
                    else:
                        print(
                            "expected an actionable Bun HTTP test failure, "
                            f"found {text}, at temporary Bun test"
                        )
                return 1

            if completed.returncode != 0:
                print(
                    "expected Bun HTTP route-group test to exit 0, "
                    f"found exit {completed.returncode}, at temporary Bun test"
                )
                return 1
            return 0
    except subprocess.TimeoutExpired:
        print("expected criterion to finish within 45 seconds, found timeout, at temporary Bun test")
        return 1
    except Exception as error:  # The criterion contract requires no traceback.
        print(
            "expected criterion execution without an exception, "
            f"found {single_line(error)}, at tests/acceptance/02-reusable-legacy-session-route-group_test.py"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
