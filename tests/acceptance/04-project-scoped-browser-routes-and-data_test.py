#!/usr/bin/env python3
"""Acceptance criterion for ticket 04: project-aware browser navigation and data."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[2]
VISUALIZER = ROOT / "apps" / "visualizer"


CLIENT_TEST = r'''
import { test } from "bun:test";
import { cpSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const source = process.env.CLIENT_SOURCE!;
const work = process.env.CLIENT_WORK!;
const result = process.env.CLIENT_RESULT!;
const failures: string[] = [];

function compact(value: unknown): string {
  let text: string;
  try { text = typeof value === "string" ? value : JSON.stringify(value); }
  catch { text = String(value); }
  return text.replace(/\s+/g, " ").slice(0, 500) || "(empty)";
}
function fail(expected: string, found: unknown, at: string): void {
  failures.push(`expected ${expected}, found ${compact(found)}, at ${at}`);
}
function check(condition: boolean, expected: string, found: unknown, at: string): void {
  if (!condition) fail(expected, found, at);
}
function same(actual: unknown, expected: unknown, at: string): void {
  check(JSON.stringify(actual) === JSON.stringify(expected), JSON.stringify(expected), actual, at);
}

test("project-bearing client routes and requests", async () => {
  try {
    const lib = join(work, "lib");
    mkdirSync(lib, { recursive: true });
    cpSync(join(source, "router.ts"), join(lib, "router.ts"));
    cpSync(join(source, "api.ts"), join(lib, "api.ts"));
    cpSync(join(source, "types.ts"), join(lib, "types.ts"));
    const vue = join(work, "node_modules", "vue");
    mkdirSync(vue, { recursive: true });
    writeFileSync(join(vue, "package.json"), JSON.stringify({ type: "module", exports: "./index.js" }));
    // Router behaviour is exercised with a tiny browser-shaped location; the
    // production Vue runtime is intentionally not part of this pure client seam.
    writeFileSync(join(vue, "index.js"), "export const ref = (value) => ({ value });\n");

    const listeners = new Map<string, Array<() => void>>();
    const location = { hash: "#/alpha%20project/run%20%2F%3F/%23phase" };
    (globalThis as Record<string, unknown>).window = {
      location,
      addEventListener(type: string, listener: () => void) {
        const items = listeners.get(type) ?? [];
        items.push(listener);
        listeners.set(type, items);
      },
    };
    const router = await import(pathToFileURL(join(lib, "router.ts")).href) as Record<string, (...args: any[]) => any>;
    for (const name of ["useRoute", "hrefFor", "navigate"]) {
      check(typeof router[name] === "function", `client router export ${name}`, typeof router[name], "apps/visualizer/src/lib/router.ts");
    }
    if (typeof router.useRoute === "function") {
      same(
        router.useRoute().value,
        { project: "alpha project", adwId: "run /?", phaseId: "#phase" },
        "parse #/<project>/<adw_id>/<phase_id>",
      );
      location.hash = "#/legacy-session";
      for (const listener of listeners.get("hashchange") ?? []) listener();
      same(
        router.useRoute().value,
        { project: "legacy-session", adwId: null, phaseId: null },
        "parse former session-only hash as a project route",
      );
    }
    if (typeof router.hrefFor === "function") {
      same(router.hrefFor("alpha project"), "#/alpha%20project/", "project list href");
      same(
        router.hrefFor("alpha project", "run /?", "#phase"),
        "#/alpha%20project/run%20%2F%3F/%23phase",
        "project session phase href encoding",
      );
    }
    if (typeof router.navigate === "function") {
      router.navigate("alpha project", "run /?", "#phase");
      same(location.hash, "#/alpha%20project/run%20%2F%3F/%23phase", "project navigation hash");
    }

    const api = await import(pathToFileURL(join(lib, "api.ts")).href) as Record<string, (...args: any[]) => Promise<unknown>>;
    const apiFunctions = [
      "fetchSessions", "fetchSession", "fetchEvents", "fetchEnvelopes", "fetchGates",
      "fetchPrompts", "fetchHealth", "archiveSession",
    ];
    for (const name of apiFunctions) {
      check(typeof api[name] === "function", `client API export ${name}`, typeof api[name], "apps/visualizer/src/lib/api.ts");
    }

    const requests: Array<{ url: string; method: string; body: string | null }> = [];
    (globalThis as Record<string, unknown>).fetch = async (input: unknown, init?: RequestInit) => {
      const url = String(input);
      requests.push({
        url,
        method: init?.method ?? "GET",
        body: typeof init?.body === "string" ? init.body : null,
      });
      let body: unknown = [];
      if (url.includes("/events?")) body = { events: [], cursor: 7, has_more: false };
      else if (url.endsWith("/health")) body = { ok: true, db: "fixture", journal_mode: "wal", sessions: 1 };
      else if (url.endsWith("/prompts")) body = { system: null, user: null };
      else if (/\/sessions\/run(?:%20|$)/.test(url)) body = {
        session: { adw_id: "run /?" }, usage: { read: 0, written: 0 }, phases: [], agents: [],
      };
      return new Response(JSON.stringify(body), { status: 200 });
    };

    const project = "alpha /? #";
    const run = "run /?";
    const agent = "agent /?";
    if (apiFunctions.every((name) => typeof api[name] === "function")) {
      await api.fetchSessions(project);
      await api.fetchSession(project, run);
      await api.fetchEvents(project, run, 7, 9);
      await api.fetchEnvelopes(project, run);
      await api.fetchGates(project, run);
      await api.fetchPrompts(project, run, agent);
      await api.fetchHealth(project);
      await api.archiveSession(project, run, false);
    }
    const base = "/api/projects/alpha%20%2F%3F%20%23";
    const expected = [
      `${base}/sessions`,
      `${base}/sessions/run%20%2F%3F`,
      `${base}/sessions/run%20%2F%3F/events?after=7&limit=9`,
      `${base}/sessions/run%20%2F%3F/envelopes`,
      `${base}/sessions/run%20%2F%3F/gates`,
      `${base}/sessions/run%20%2F%3F/agents/agent%20%2F%3F/prompts`,
      `${base}/health`,
      `${base}/sessions/run%20%2F%3F/archive`,
    ];
    same(requests.map((request) => request.url), expected, "all project-bound client request URLs");
    const archive = requests.at(-1);
    check(archive?.method === "POST", "POST archive request", archive, "archive client mutation");
    same(archive?.body, JSON.stringify({ archived: false }), "archive mutation body", "archive client mutation");
  } catch (error) {
    fail("client route and API criterion to complete without an exception", error instanceof Error ? error.message : String(error), "temporary Bun client test");
  } finally {
    await Bun.write(result, JSON.stringify(failures));
    if (failures.length) process.exitCode = 1;
  }
});
'''


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], directory: Path):
        super().__init__(address, FixtureHandler)
        self.directory = directory.resolve()
        self.mode = "multi"
        self.logs: list[dict[str, Any]] = []
        self.log_lock = threading.Lock()

    def projects(self) -> tuple[list[str], str]:
        return (["solo"], "solo") if self.mode == "single" else (["alpha", "beta"], "alpha")

    def clear_logs(self) -> None:
        with self.log_lock:
            self.logs.clear()

    def request_logs(self) -> list[dict[str, Any]]:
        with self.log_lock:
            return list(self.logs)

    def note(self, method: str, raw_path: str) -> None:
        with self.log_lock:
            self.logs.append({"method": method, "path": raw_path})


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def phase(project: str) -> dict[str, object]:
        label = project.upper()
        return {
            "phase_id": f"phase-{project}", "adw_id": "collision", "seq": 1,
            "name": f"{label} PHASE", "kind": "agent", "owner": "worker",
            "description": f"{label} phase description", "status": "success",
            "attempt": 1, "retries": 0, "error": None,
            "started_at": "2025-01-02T03:04:05.000Z", "ended_at": "2025-01-02T03:14:05.000Z",
        }

    @classmethod
    def summary(cls, project: str) -> dict[str, object]:
        label = project.upper()
        phase = cls.phase(project)
        return {
            "adw_id": "collision", "adw_name": f"{label} flow", "request": f"{label} CARD",
            "status": "success", "engineer": "fixture", "started_at": "2025-01-02T03:04:05.000Z",
            "ended_at": "2025-01-02T03:14:05.000Z", "total_tokens": 42, "total_cost": 1.25,
            "archived": 0, "phases": [phase], "phase_count": 1,
            "agents": [{"adw_id": "collision", "agent": "worker", "coding_agent": "pi",
                        "model": f"{project}-model", "session_id": f"{project}-worker",
                        "color": "#abcdef", "context_tokens": 50, "context_window": 100,
                        "created_at": None, "last_used_at": None}],
        }

    @classmethod
    def detail(cls, project: str) -> dict[str, object]:
        label = project.upper()
        summary = cls.summary(project)
        session_keys = [
            "adw_id", "adw_name", "request", "status", "engineer", "started_at", "ended_at",
            "total_tokens", "total_cost", "archived",
        ]
        return {
            "session": {key: summary[key] for key in session_keys} | {"request": f"{label} TRACE"},
            "usage": {"read": 2, "written": 3}, "phases": [cls.phase(project)],
            "agents": summary["agents"],
        }

    def do_POST(self) -> None:
        self.server.note("POST", self.path)
        path = unquote(urlparse(self.path).path)
        if path.endswith("/archive") and self.project_for(path) is not None:
            self.json({"adw_id": "collision", "archived": True})
        else:
            self.json({"error": "not found"}, 404)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.server.note("GET", self.path)
            self.api(path, parsed.query)
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (self.server.directory / relative).resolve()
        if candidate != self.server.directory and self.server.directory not in candidate.parents:
            self.send_error(404)
            return
        if not candidate.is_file():
            candidate = self.server.directory / "index.html"
        if not candidate.is_file():
            self.send_error(404)
            return
        content = candidate.read_bytes()
        self.send_response(200)
        self.send_header("content-type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("content-length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def project_for(self, path: str) -> str | None:
        parts = path.split("/")
        # /api/projects/<project>/...
        if len(parts) < 5 or parts[1:3] != ["api", "projects"]:
            return None
        project = parts[3]
        projects, _default = self.server.projects()
        return project if project in projects else None

    def api(self, path: str, _query: str) -> None:
        if path == "/api/projects":
            projects, default = self.server.projects()
            self.json({
                "projects": [
                    {"name": name, "location": f"/fixture/{name}/mill.db", "available": True,
                     "availabilityError": None}
                    for name in projects
                ],
                "defaultProjectName": default,
            })
            return
        project = self.project_for(path)
        if project is None:
            self.json({"error": "unknown project"}, 404)
            return
        prefix = f"/api/projects/{project}"
        suffix = path[len(prefix):]
        # A late alpha trace response makes a missing project-inclusive key
        # visibly leak stale data after switching to beta with the same adw_id.
        if project == "alpha" and suffix.startswith("/sessions/collision"):
            time.sleep(0.35)
        if suffix == "/health":
            self.json({"ok": True, "db": f"/fixture/{project}/mill.db", "journal_mode": "wal", "sessions": 1})
        elif suffix == "/sessions":
            self.json([self.summary(project)])
        elif suffix == "/sessions/collision":
            self.json(self.detail(project))
        elif suffix == "/sessions/collision/events":
            self.json({"events": [{
                "rowid": 1, "event_id": f"event-{project}", "adw_id": "collision",
                "phase_id": f"phase-{project}", "parent_id": None, "type": "agent_start",
                "name": f"{project} worker", "payload_json": "{}", "tokens": 1,
                "started_at": "2025-01-02T03:05:05.000Z", "ended_at": None,
            }], "cursor": 1, "has_more": False})
        elif suffix == "/sessions/collision/envelopes":
            self.json([{"envelope_id": f"envelope-{project}", "adw_id": "collision",
                        "phase_id": f"phase-{project}", "agent": "worker", "output_type": f"{project}Output",
                        "payload_json": "{}", "valid": 1, "attempt": 1, "created_at": None}])
        elif suffix == "/sessions/collision/gates":
            self.json([{"id": 1, "adw_id": "collision", "phase_id": f"phase-{project}", "attempt": 1,
                        "gate": f"{project}_gate", "passed": 1, "violations_json": "[]",
                        "checks_json": "[]", "created_at": None}])
        elif suffix == "/sessions/collision/agents/worker/prompts":
            self.json({"system": f"{project} system prompt", "user": f"{project} user prompt"})
        else:
            self.json({"error": "not found"}, 404)


class DevTools:
    """Minimal CDP client using only the standard library (no test dependency)."""

    def __init__(self, endpoint: str):
        parsed = urlparse(endpoint)
        self.sock = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=5)
        self.sock.settimeout(5)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {parsed.path or '/'} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n\r\n"
        ).encode("ascii")
        self.sock.sendall(request)
        response = self._read_http_headers()
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"DevTools websocket upgrade failed: {response[:200]!r}")
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    def _read_http_headers(self) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            block = self.sock.recv(1024)
            if not block:
                raise RuntimeError("DevTools websocket closed during upgrade")
            data += block
        return data

    def _recv_exact(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            part = self.sock.recv(count - len(data))
            if not part:
                raise RuntimeError("DevTools websocket closed")
            data += part
        return data

    def _send_frame(self, payload: bytes, opcode: int = 1) -> None:
        mask = secrets.token_bytes(4)
        size = len(payload)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", size)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def _recv_frame(self) -> dict[str, Any] | None:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._recv_exact(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(size)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if opcode == 9:
            self._send_frame(payload, 10)
            return None
        if opcode == 8:
            raise RuntimeError("DevTools websocket closed")
        if opcode != 1:
            return None
        return json.loads(payload.decode("utf-8"))

    def command(self, method: str, params: dict[str, Any] | None = None, session: str | None = None) -> dict[str, Any]:
        identifier = self.next_id
        self.next_id += 1
        message: dict[str, Any] = {"id": identifier, "method": method}
        if params is not None:
            message["params"] = params
        if session is not None:
            message["sessionId"] = session
        self._send_frame(json.dumps(message, separators=(",", ":")).encode("utf-8"))
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline:
            event = self._recv_frame()
            if event is None:
                continue
            if event.get("id") == identifier:
                if "error" in event:
                    raise RuntimeError(f"CDP {method}: {event['error']}")
                return event.get("result", {})
            self.events.append(event)
        raise RuntimeError(f"timed out waiting for CDP {method}")

    def wait_event(self, method: str, session: str, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for index, event in enumerate(self.events):
                if event.get("method") == method and event.get("sessionId") == session:
                    self.events.pop(index)
                    return
            event = self._recv_frame()
            if event is not None:
                self.events.append(event)
        raise RuntimeError(f"timed out waiting for CDP event {method}")

    def close(self) -> None:
        try:
            self._send_frame(b"", 8)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def one_line(value: object) -> str:
    return " ".join(str(value).split())[:500] or "(empty)"


def failure_line(value: object) -> str:
    """Keep the required expected/found/at envelope even for bulky fixtures."""
    text = " ".join(str(value).split())
    if text.startswith("expected ") and ", found " in text and ", at " in text:
        expected, remainder = text[len("expected "):].split(", found ", 1)
        found, at = remainder.rsplit(", at ", 1)
        return f"expected {expected[:180] or '(empty)'}, found {found[:220] or '(empty)'}, at {at[:100] or '(empty)'}"
    return f"expected actionable project-browser result, found {text[:260] or '(empty)'}, at acceptance criterion"


def frontend_modules() -> Path | None:
    candidates = [VISUALIZER / "node_modules"]
    # The checked-out source intentionally ignores node_modules. This workspace
    # has the same repository's installed toolchain beside the worktree; discover
    # it rather than downloading anything or mutating the project under test.
    try:
        development_root = ROOT.parents[1]
        candidates.extend(path / "apps" / "visualizer" / "node_modules" for path in development_root.iterdir())
    except (IndexError, OSError):
        pass
    for candidate in candidates:
        if (candidate / ".bin" / "vue-tsc").is_file() and (candidate / ".bin" / "vite").is_file():
            return candidate
    return None


def run(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=False)


def run_client_seam(temp: Path) -> list[str]:
    test_path = temp / "client-routes.test.ts"
    result_path = temp / "client-results.json"
    test_path.write_text(CLIENT_TEST, encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "CLIENT_SOURCE": str(VISUALIZER / "src" / "lib"),
        "CLIENT_WORK": str(temp / "client-work"),
        "CLIENT_RESULT": str(result_path),
    })
    completed = subprocess.run(["bun", "test", str(test_path)], cwd=VISUALIZER, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    if result_path.is_file():
        try:
            loaded = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                return [failure_line(item) for item in loaded]
        except (OSError, json.JSONDecodeError):
            pass
    return [f"expected Bun client route test to write focused results, found exit {completed.returncode}, at temporary Bun client test"]


def copy_visualizer(temp: Path, modules: Path) -> tuple[Path, Path]:
    copied = temp / "visualizer"
    shutil.copytree(VISUALIZER, copied, ignore=shutil.ignore_patterns("node_modules", "dist"))
    os.symlink(modules, copied / "node_modules", target_is_directory=True)
    output = temp / "production-build"
    return copied, output


def start_fixture_server(directory: Path) -> tuple[FixtureServer, threading.Thread, str]:
    server = FixtureServer(("127.0.0.1", 0), directory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_port}"


def chrome_binary() -> Path | None:
    cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    shells = sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell"))
    if shells:
        return shells[-1]
    google = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return google if google.is_file() else None


def free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    return port


def start_chrome(temp: Path) -> tuple[subprocess.Popen[bytes], DevTools]:
    chrome = chrome_binary()
    if chrome is None:
        raise RuntimeError("no local Chrome or Chromium headless shell")
    port = free_port()
    process = subprocess.Popen(
        [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
         f"--user-data-dir={temp / 'chrome-profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    endpoint: str | None = None
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
                endpoint = json.loads(response.read().decode("utf-8")).get("webSocketDebuggerUrl")
            if isinstance(endpoint, str):
                return process, DevTools(endpoint)
        except OSError:
            time.sleep(0.05)
    process.kill()
    raise RuntimeError("Chrome did not expose a DevTools endpoint")


def create_page(cdp: DevTools, url: str) -> tuple[str, str]:
    target = cdp.command("Target.createTarget", {"url": "about:blank"})["targetId"]
    attached = cdp.command("Target.attachToTarget", {"targetId": target, "flatten": True})
    session = attached["sessionId"]
    cdp.command("Page.enable", session=session)
    cdp.command("Runtime.enable", session=session)
    cdp.command("Page.navigate", {"url": url}, session=session)
    cdp.wait_event("Page.loadEventFired", session)
    return str(target), str(session)


def evaluate(cdp: DevTools, session: str, expression: str) -> Any:
    outcome = cdp.command("Runtime.evaluate", {
        "expression": expression, "awaitPromise": True, "returnByValue": True,
    }, session=session)
    result = outcome.get("result", {})
    if "exceptionDetails" in outcome:
        raise RuntimeError(str(outcome["exceptionDetails"]))
    if result.get("subtype") == "error":
        raise RuntimeError(result.get("description", "browser evaluation error"))
    return result.get("value")


def snapshot_when(cdp: DevTools, session: str, needle: str, seconds: float = 2.5) -> dict[str, Any]:
    expression = f'''(async () => {{
      const until = Date.now() + {int(seconds * 1000)};
      while (Date.now() < until && !document.body.innerText.includes({json.dumps(needle)})) {{
        await new Promise((resolve) => setTimeout(resolve, 20));
      }}
      const crumbs = document.querySelector('.crumbs');
      return {{
        found: document.body.innerText.includes({json.dumps(needle)}),
        hash: location.hash,
        body: document.body.innerText,
        crumbs: crumbs ? crumbs.innerText : '',
        cardHref: document.querySelector('.card')?.getAttribute('href') ?? null,
        projectControls: document.querySelectorAll('.crumbs select, .crumbs [role="combobox"], .crumbs [role="listbox"], .crumbs button[aria-haspopup]').length,
      }};
    }})()'''
    value = evaluate(cdp, session, expression)
    return value if isinstance(value, dict) else {"found": False, "body": value}


def wait_for_request(server: FixtureServer, predicate: Any, seconds: float = 2.5) -> list[dict[str, Any]]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        entries = server.request_logs()
        if predicate(entries):
            return entries
        time.sleep(0.02)
    return server.request_logs()


def has_path(entries: list[dict[str, Any]], path: str, method: str = "GET") -> bool:
    return any(entry["method"] == method and entry["path"] == path for entry in entries)


def assert_scoped_requests(failures: list[str], entries: list[dict[str, Any]], at: str) -> None:
    unscoped = [entry for entry in entries if entry["path"].startswith("/api/") and not entry["path"].startswith("/api/projects")]
    if unscoped:
        failures.append(f"expected every browser UI request to use a project-prefixed API URL, found {one_line(unscoped)}, at {at}")


def browser_checks(temp: Path, dist: Path, failures: list[str]) -> None:
    server, thread, base = start_fixture_server(dist)
    chrome: subprocess.Popen[bytes] | None = None
    cdp: DevTools | None = None
    targets: list[str] = []
    try:
        chrome, cdp = start_chrome(temp)

        # Bare root resolves the server-reported default before loading its list.
        server.clear_logs()
        root_target, page = create_page(cdp, f"{base}/#/")
        targets.append(root_target)
        root = snapshot_when(cdp, page, "ALPHA CARD")
        if not root.get("found"):
            failures.append(f"expected root hash to load default project alpha sessions, found {one_line(root.get('body'))}, at browser #/")
        if root.get("hash") != "#/alpha/":
            failures.append(f"expected root hash redirect #/alpha/, found {one_line(root.get('hash'))}, at browser #/")
        if root.get("cardHref") != "#/alpha/collision":
            failures.append(f"expected alpha session link retaining project segment, found {one_line(root.get('cardHref'))}, at browser alpha session card")
        if "alpha" not in str(root.get("crumbs", "")):
            failures.append(f"expected selected project alpha in navigation, found {one_line(root.get('crumbs'))}, at browser default-project breadcrumbs")
        requests = wait_for_request(server, lambda entries: has_path(entries, "/api/projects/alpha/sessions"))
        if not has_path(requests, "/api/projects") or not has_path(requests, "/api/projects/alpha/sessions"):
            failures.append(f"expected project listing then default alpha scoped sessions request, found {one_line(requests)}, at browser root data load")
        assert_scoped_requests(failures, requests, "browser root data load")

        # A legacy one-segment hash denotes a project now, never an adw in alpha.
        server.clear_logs()
        evaluate(cdp, page, "location.hash = '#/collision'")
        requests = wait_for_request(server, lambda entries: any("collision" in entry["path"] for entry in entries))
        if not has_path(requests, "/api/projects/collision/sessions"):
            failures.append(f"expected former session-only #/collision to request collision as a project, found {one_line(requests)}, at browser legacy hash")
        if any(entry["path"].startswith("/api/projects/alpha/sessions/collision") for entry in requests):
            failures.append(f"expected no alpha session lookup for former session-only hash, found {one_line(requests)}, at browser legacy hash")
        assert_scoped_requests(failures, requests, "browser legacy hash")

        # Same adw_id cards must remount with beta's list and write through beta.
        server.clear_logs()
        evaluate(cdp, page, "location.hash = '#/alpha/'")
        alpha_list = snapshot_when(cdp, page, "ALPHA CARD")
        if not alpha_list.get("found"):
            failures.append(f"expected alpha list card before project switch, found {one_line(alpha_list.get('body'))}, at browser alpha list")
        evaluate(cdp, page, "location.hash = '#/beta/'")
        beta_list = snapshot_when(cdp, page, "BETA CARD")
        time.sleep(0.65)
        beta_list = snapshot_when(cdp, page, "BETA CARD", 0.1)
        if not beta_list.get("found") or "ALPHA CARD" in str(beta_list.get("body", "")):
            failures.append(f"expected beta-only card state after switching projects with collision adw_id, found {one_line(beta_list.get('body'))}, at browser project list switch")
        requests = wait_for_request(server, lambda entries: has_path(entries, "/api/projects/beta/sessions"))
        if not has_path(requests, "/api/projects/beta/sessions"):
            failures.append(f"expected beta scoped list request after project switch, found {one_line(requests)}, at browser project list switch")
        assert_scoped_requests(failures, requests, "browser project list switch")
        evaluate(cdp, page, "document.querySelector('.card-archive')?.click()")
        requests = wait_for_request(server, lambda entries: has_path(entries, "/api/projects/beta/sessions/collision/archive", "POST"))
        if not has_path(requests, "/api/projects/beta/sessions/collision/archive", "POST"):
            failures.append(f"expected beta scoped archive action for collision, found {one_line(requests)}, at browser session card archive")
        assert_scoped_requests(failures, requests, "browser session card archive")

        # Delay alpha so an implementation keyed only by adw_id leaks its old
        # trace, cursor, phase and local detail state into beta.
        server.clear_logs()
        evaluate(cdp, page, "location.hash = '#/alpha/collision/phase-alpha'")
        snapshot_when(cdp, page, "loading trace…", 1.0)
        time.sleep(0.05)
        evaluate(cdp, page, "location.hash = '#/beta/collision/phase-beta'")
        beta_trace = snapshot_when(cdp, page, "BETA TRACE")
        time.sleep(0.55)
        beta_trace = snapshot_when(cdp, page, "BETA TRACE", 0.1)
        trace_body = str(beta_trace.get("body", ""))
        if not beta_trace.get("found") or "ALPHA TRACE" in trace_body or "ALPHA PHASE" in trace_body:
            failures.append(f"expected beta-only trace, phase, cursor and detail state after collision switch, found {one_line(trace_body)}, at browser trace project switch")
        crumbs = str(beta_trace.get("crumbs", ""))
        beta_at, run_at, phase_at = crumbs.find("beta"), crumbs.find("collision"), crumbs.find("BETA PHASE")
        if min(beta_at, run_at, phase_at) < 0 or not beta_at < run_at < phase_at:
            failures.append(f"expected project, session, then phase breadcrumbs for beta, found {one_line(crumbs)}, at browser trace breadcrumbs")
        requests = wait_for_request(server, lambda entries: has_path(entries, "/api/projects/beta/sessions/collision/agents/worker/prompts"))
        required = [
            "/api/projects/beta/sessions/collision",
            "/api/projects/beta/sessions/collision/events?after=0&limit=1000",
            "/api/projects/beta/sessions/collision/envelopes",
            "/api/projects/beta/sessions/collision/gates",
            "/api/projects/beta/sessions/collision/agents/worker/prompts",
        ]
        absent = [path for path in required if not has_path(requests, path)]
        if absent:
            failures.append(f"expected scoped beta trace, event-tail, envelope, gate and prompt reads, found {one_line({'missing': absent, 'requests': requests})}, at browser phase route")
        assert_scoped_requests(failures, requests, "browser phase route")
        cdp.command("Target.closeTarget", {"targetId": root_target})

        # Exactly one configured project stays a label in the breadcrumb, not a picker.
        server.mode = "single"
        server.clear_logs()
        single_target, single_page = create_page(cdp, f"{base}/#/")
        targets.append(single_target)
        single = snapshot_when(cdp, single_page, "SOLO CARD")
        if not single.get("found") or single.get("hash") != "#/solo/":
            failures.append(f"expected root to redirect and load sole project solo, found {one_line(single)}, at browser single-project root")
        if "solo" not in str(single.get("crumbs", "")) or single.get("projectControls") != 0:
            failures.append(f"expected sole project name as plain breadcrumb text without a selector, found {one_line({'crumbs': single.get('crumbs'), 'controls': single.get('projectControls')})}, at browser single-project navigation")
    except Exception as error:
        failures.append(f"expected production browser criterion to complete without an exception, found {one_line(error)}, at temporary Chrome browser test")
    finally:
        if cdp is not None:
            for target in targets:
                try:
                    cdp.command("Target.closeTarget", {"targetId": target})
                except Exception:
                    pass
            cdp.close()
        if chrome is not None:
            try:
                chrome.terminate()
                chrome.wait(timeout=3)
            except Exception:
                try:
                    chrome.kill()
                except Exception:
                    pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> int:
    failures: list[str] = []
    try:
        if not VISUALIZER.is_dir():
            print("expected visualizer project directory, found missing, at apps/visualizer")
            return 1
        modules = frontend_modules()
        if modules is None:
            print("expected an existing local visualizer Vue/Vite toolchain, found no node_modules with vue-tsc and vite, at apps/visualizer")
            return 1

        with tempfile.TemporaryDirectory(prefix="mill-project-browser-criterion-") as temporary:
            temp = Path(temporary)
            for failure in run_client_seam(temp):
                failures.append(failure)

            copied, output = copy_visualizer(temp, modules)
            typecheck = run(["bun", "run", "typecheck"], copied, 20)
            if typecheck.returncode != 0:
                failures.append(
                    f"expected visualizer typecheck to exit 0, found exit {typecheck.returncode}: {one_line(typecheck.stderr or typecheck.stdout)}, at apps/visualizer typecheck"
                )
            build = run(["bun", "run", "build", "--", "--outDir", str(output)], copied, 25)
            if build.returncode != 0 or not (output / "index.html").is_file():
                found = f"exit {build.returncode}: {one_line(build.stderr or build.stdout)}"
                failures.append(f"expected visualizer production build with index.html, found {found}, at apps/visualizer build")
            else:
                browser_checks(temp, output, failures)

        if failures:
            for failure in failures:
                print(failure_line(failure))
            return 1
        return 0
    except subprocess.TimeoutExpired:
        print("expected criterion to finish within 55 seconds, found timeout, at tests/acceptance/04-project-scoped-browser-routes-and-data_test.py")
        return 1
    except Exception as error:
        print(f"expected criterion execution without an exception, found {one_line(error)}, at tests/acceptance/04-project-scoped-browser-routes-and-data_test.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
