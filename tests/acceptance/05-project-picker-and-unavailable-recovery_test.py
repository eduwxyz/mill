#!/usr/bin/env python3
"""Acceptance criterion for ticket 05: project picker and unavailable recovery."""

from __future__ import annotations

import base64
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]
VISUALIZER = ROOT / "apps" / "visualizer"


class PickerFixtureServer(ThreadingHTTPServer):
    """A browser-facing project API whose availability can change in-process."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], directory: Path):
        super().__init__(address, PickerFixtureHandler)
        self.directory = directory.resolve()
        self.mode = "multi"
        self.sleepy_available = False
        self.logs: list[dict[str, str]] = []
        self.log_lock = threading.Lock()

    def names(self) -> list[str]:
        return ["solo"] if self.mode == "single" else ["alpha", "beta", "sleepy"]

    def projects_payload(self) -> dict[str, object]:
        if self.mode == "single":
            return {
                "projects": [{
                    "name": "solo", "location": "/fixture/solo/mill.db",
                    "available": True, "availabilityError": None,
                }],
                "defaultProjectName": "solo",
            }
        sleepy_error = None if self.sleepy_available else "configured project sleepy is temporarily unavailable"
        return {
            "projects": [
                {"name": "alpha", "location": "/fixture/alpha/mill.db", "available": True, "availabilityError": None},
                {"name": "beta", "location": "/fixture/beta/mill.db", "available": True, "availabilityError": None},
                {
                    "name": "sleepy", "location": "/fixture/sleepy/mill.db",
                    "available": self.sleepy_available, "availabilityError": sleepy_error,
                },
            ],
            "defaultProjectName": "alpha",
        }

    def note(self, method: str, raw_path: str) -> None:
        with self.log_lock:
            self.logs.append({"method": method, "path": raw_path})

    def entries(self) -> list[dict[str, str]]:
        with self.log_lock:
            return list(self.logs)

    def count(self, path: str, method: str = "GET") -> int:
        with self.log_lock:
            return sum(item["method"] == method and item["path"] == path for item in self.logs)


class PickerFixtureHandler(BaseHTTPRequestHandler):
    server: PickerFixtureServer

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def respond_json(self, value: object, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def summary(project: str) -> dict[str, object]:
        return {
            "adw_id": f"{project}-run", "adw_name": f"{project}-flow",
            "request": f"{project.upper()} SESSION", "status": "success",
            "engineer": "fixture", "started_at": "2025-01-02T03:04:05.000Z",
            "ended_at": "2025-01-02T03:14:05.000Z", "total_tokens": 42,
            "total_cost": 1.25, "archived": 0, "phases": [], "phase_count": 0,
            "agents": [],
        }

    def project_for(self, path: str) -> str | None:
        parts = path.split("/")
        if len(parts) < 5 or parts[1:3] != ["api", "projects"]:
            return None
        return parts[3] if parts[3] in self.server.names() else None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            self.server.note("GET", self.path)
            self.api(path)
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
        body = candidate.read_bytes()
        self.send_response(200)
        self.send_header("content-type", mimetypes.guess_type(candidate.name)[0] or "application/octet-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api(self, path: str) -> None:
        if path == "/api/projects":
            self.respond_json(self.server.projects_payload())
            return

        project = self.project_for(path)
        if project is None:
            self.respond_json({"error": "unknown configured project"}, 404)
            return
        prefix = f"/api/projects/{project}"
        suffix = path[len(prefix):]
        if project == "sleepy" and not self.server.sleepy_available:
            self.respond_json({"error": "configured project sleepy is temporarily unavailable"}, 503)
            return
        if suffix == "/sessions":
            self.respond_json([self.summary(project)])
        elif suffix.startswith("/sessions/") and suffix.endswith("/events"):
            self.respond_json({"events": [], "cursor": 0, "has_more": False})
        else:
            self.respond_json({"error": "not found"}, 404)


class DevTools:
    """Small CDP client using only the standard library."""

    def __init__(self, endpoint: str):
        parsed = urlparse(endpoint)
        self.socket = socket.create_connection((parsed.hostname or "127.0.0.1", parsed.port or 80), timeout=4)
        self.socket.settimeout(4)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {parsed.path or '/'} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n"
            "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
            f"Sec-WebSocket-Key: {key}\r\n\r\n"
        ).encode("ascii")
        self.socket.sendall(request)
        headers = self._headers()
        if b" 101 " not in headers.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"DevTools websocket upgrade failed: {headers[:180]!r}")
        self.next_id = 1
        self.events: list[dict[str, Any]] = []

    def _headers(self) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.socket.recv(1024)
            if not chunk:
                raise RuntimeError("DevTools websocket closed during upgrade")
            data += chunk
        return data

    def _exact(self, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = self.socket.recv(length - len(data))
            if not chunk:
                raise RuntimeError("DevTools websocket closed")
            data += chunk
        return data

    def _send(self, payload: bytes, opcode: int = 1) -> None:
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = bytes([0x80 | opcode])
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", length)
        encoded = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        self.socket.sendall(header + mask + encoded)

    def _receive(self) -> dict[str, Any] | None:
        first, second = self._exact(2)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._exact(8))[0]
        mask = self._exact(4) if masked else b""
        payload = self._exact(length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if opcode == 9:
            self._send(payload, 10)
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
        self._send(json.dumps(message, separators=(",", ":")).encode("utf-8"))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            event = self._receive()
            if event is None:
                continue
            if event.get("id") == identifier:
                if "error" in event:
                    raise RuntimeError(f"CDP {method}: {event['error']}")
                return event.get("result", {})
            self.events.append(event)
        raise RuntimeError(f"timed out waiting for CDP {method}")

    def wait_event(self, method: str, session: str, seconds: float = 3) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for index, event in enumerate(self.events):
                if event.get("method") == method and event.get("sessionId") == session:
                    self.events.pop(index)
                    return
            event = self._receive()
            if event is not None:
                self.events.append(event)
        raise RuntimeError(f"timed out waiting for CDP event {method}")

    def close(self) -> None:
        try:
            self._send(b"", 8)
        except OSError:
            pass
        try:
            self.socket.close()
        except OSError:
            pass


def compact(value: object) -> str:
    return " ".join(str(value).split())[:500] or "(empty)"


def failure(expected: str, found: object, at: str) -> str:
    return f"expected {expected}, found {compact(found)}, at {at}"


def chrome_binary() -> Path | None:
    cached = sorted((Path.home() / "Library" / "Caches" / "ms-playwright").glob(
        "chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell",
    ))
    if cached:
        return cached[-1]
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    return chrome if chrome.is_file() else None


def frontend_modules() -> Path | None:
    candidates = [VISUALIZER / "node_modules"]
    # node_modules is intentionally ignored in worktrees. Look for an already
    # installed sibling checkout rather than downloading or changing the source.
    for ancestor in ROOT.parents:
        try:
            candidates.extend(child / "apps" / "visualizer" / "node_modules" for child in ancestor.iterdir())
        except OSError:
            continue
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / ".bin" / "vite").is_file() and (candidate / ".bin" / "vue-tsc").is_file():
            return candidate
    return None


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
        [
            str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}", f"--user-data-dir={temp / 'chrome-profile'}", "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.4) as response:
                endpoint = json.loads(response.read().decode("utf-8")).get("webSocketDebuggerUrl")
            if isinstance(endpoint, str):
                return process, DevTools(endpoint)
        except OSError:
            time.sleep(0.04)
    process.kill()
    raise RuntimeError("Chrome did not expose a DevTools endpoint")


def create_page(cdp: DevTools, url: str) -> tuple[str, str]:
    target = str(cdp.command("Target.createTarget", {"url": "about:blank"})["targetId"])
    session = str(cdp.command("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"])
    cdp.command("Page.enable", session=session)
    cdp.command("Runtime.enable", session=session)
    cdp.command("Page.navigate", {"url": url}, session=session)
    cdp.wait_event("Page.loadEventFired", session)
    return target, session


def evaluate(cdp: DevTools, session: str, expression: str) -> Any:
    result = cdp.command(
        "Runtime.evaluate",
        {"expression": expression, "awaitPromise": True, "returnByValue": True},
        session=session,
    )
    if "exceptionDetails" in result:
        raise RuntimeError(str(result["exceptionDetails"]))
    value = result.get("result", {})
    if value.get("subtype") == "error":
        raise RuntimeError(str(value.get("description", "browser evaluation error")))
    return value.get("value")


def page_state(cdp: DevTools, session: str) -> dict[str, Any]:
    value = evaluate(cdp, session, """(() => {
      const picker = document.querySelector('header select');
      return {
        hash: location.hash,
        main: document.querySelector('main')?.innerText ?? '',
        header: document.querySelector('header')?.innerText ?? '',
        picker: picker ? {
          value: picker.value,
          options: [...picker.options].map((option) => option.textContent?.trim() ?? ''),
        } : null,
      };
    })()""")
    return value if isinstance(value, dict) else {"main": value}


def wait_for_text(cdp: DevTools, session: str, text: str, seconds: float = 1.8) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = page_state(cdp, session)
        if text in str(latest.get("main", "")):
            return latest
        time.sleep(0.035)
    return latest


def wait_for_count(server: PickerFixtureServer, path: str, greater_than: int, seconds: float = 1.8) -> int:
    deadline = time.monotonic() + seconds
    count = server.count(path)
    while time.monotonic() < deadline:
        count = server.count(path)
        if count > greater_than:
            return count
        time.sleep(0.02)
    return count


def picker_open(cdp: DevTools, session: str) -> object:
    # mousedown/focus/click are the browser actions that open the existing
    # native picker; handlers may reasonably subscribe to any of them.
    return evaluate(cdp, session, """(() => {
      const picker = document.querySelector('header select');
      if (!picker) return null;
      picker.focus();
      picker.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      picker.click();
      return picker.options.length;
    })()""")


def picker_select(cdp: DevTools, session: str, project: str) -> object:
    return evaluate(cdp, session, f"""(() => {{
      const picker = document.querySelector('header select');
      if (!picker) return null;
      picker.value = {json.dumps(project)};
      picker.dispatchEvent(new Event('change', {{ bubbles: true }}));
      return picker.value;
    }})()""")


def entry_has_status(entries: object, name: str, available: bool) -> bool:
    if not isinstance(entries, list):
        return False
    wanted = r"\\b(available|ready|online)\\b" if available else r"\\b(unavailable|offline|missing|not\\s+available)\\b"
    import re
    return any(re.search(rf"\\b{re.escape(name)}\\b", str(entry), re.I) and re.search(wanted, str(entry), re.I) for entry in entries)


def browser_checks(temp: Path, output: Path, failures: list[str]) -> None:
    server = PickerFixtureServer(("127.0.0.1", 0), output)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    chrome: subprocess.Popen[bytes] | None = None
    cdp: DevTools | None = None
    targets: list[str] = []
    try:
        chrome, cdp = start_chrome(temp)
        target, page = create_page(cdp, f"{base}/#/alpha/")
        targets.append(target)
        initial = wait_for_text(cdp, page, "ALPHA SESSION")
        if "ALPHA SESSION" not in str(initial.get("main", "")):
            failures.append(failure("alpha sessions at the configured alpha route", initial, "browser #/alpha/"))
        if initial.get("picker") is None:
            failures.append(failure("a project picker with more than one configured project", initial.get("header"), "browser multi-project top bar"))
            return
        options = initial.get("picker", {}).get("options") if isinstance(initial.get("picker"), dict) else None
        for name, available in [("alpha", True), ("beta", True), ("sleepy", False)]:
            if not entry_has_status(options, name, available):
                failures.append(failure(
                    f"picker entry for {name} showing it as {'available' if available else 'unavailable'}",
                    options,
                    "browser project-picker entries",
                ))

        # Session polling is intentional, but GET /api/projects must not be a
        # background availability poll while the picker stays closed.
        listed_initially = server.count("/api/projects")
        time.sleep(0.8)
        listed_while_closed = server.count("/api/projects")
        if listed_while_closed != listed_initially:
            failures.append(failure(
                "no project-list refresh while the picker remains closed",
                f"{listed_while_closed} GET /api/projects requests after {listed_initially} initial requests",
                "browser multi-project idle state",
            ))

        before_open = server.count("/api/projects")
        opened = picker_open(cdp, page)
        if opened is None:
            failures.append(failure("an operable project picker", "no header select", "browser project-picker open"))
        after_open = wait_for_count(server, "/api/projects", before_open)
        if after_open <= before_open:
            failures.append(failure(
                "GET /api/projects when the project picker opens",
                f"{after_open} requests (before opening: {before_open})",
                "browser project-picker open",
            ))

        # Choosing an available project must be a root project route, rather
        # than retaining alpha's route or card state.
        picked_beta = picker_select(cdp, page, "beta")
        beta = wait_for_text(cdp, page, "BETA SESSION")
        if picked_beta != "beta" or beta.get("hash") != "#/beta/":
            failures.append(failure("selection of beta to navigate to root hash #/beta/", {"selected": picked_beta, "hash": beta.get("hash")}, "browser available project selection"))
        if "BETA SESSION" not in str(beta.get("main", "")) or "ALPHA SESSION" in str(beta.get("main", "")):
            failures.append(failure("only beta sessions after selecting beta", beta.get("main"), "browser available project selection"))
        if server.count("/api/projects/beta/sessions") < 1:
            failures.append(failure("a scoped beta sessions request after selecting beta", server.entries(), "browser available project selection"))

        # A configured unavailable project is selected through the same picker;
        # its 503 must be named to the user and must refresh the picker.
        before_unavailable = server.count("/api/projects")
        picked_sleepy = picker_select(cdp, page, "sleepy")
        unavailable = wait_for_text(cdp, page, "503")
        if picked_sleepy != "sleepy" or unavailable.get("hash") != "#/sleepy/":
            failures.append(failure("selection of sleepy to navigate to root hash #/sleepy/", {"selected": picked_sleepy, "hash": unavailable.get("hash")}, "browser unavailable project selection"))
        if server.count("/api/projects/sleepy/sessions") < 1:
            failures.append(failure("a scoped sleepy sessions request", server.entries(), "browser unavailable project selection"))
        unavailable_main = str(unavailable.get("main", ""))
        import re
        if not re.search(r"\\b(unavailable|temporarily unavailable|not available|offline|missing)\\b", unavailable_main, re.I):
            failures.append(failure("a clear temporarily unavailable project outcome", unavailable_main, "browser unavailable project selection"))
        if re.search(r"\\bunknown\\b", unavailable_main, re.I):
            failures.append(failure("an unavailable outcome distinct from unknown-project", unavailable_main, "browser unavailable project selection"))
        after_unavailable = wait_for_count(server, "/api/projects", before_unavailable)
        if after_unavailable <= before_unavailable:
            failures.append(failure(
                "picker refresh after the scoped sleepy 503 response",
                f"{after_unavailable} GET /api/projects requests (before 503: {before_unavailable})",
                "browser unavailable project selection",
            ))

        # Move away before the fixture database appears, then create it without
        # restarting the server. Opening the picker must reveal its new status
        # and selecting it must work in this same browser/server session.
        picker_select(cdp, page, "beta")
        wait_for_text(cdp, page, "BETA SESSION")
        server.sleepy_available = True
        before_reopen = server.count("/api/projects")
        picker_open(cdp, page)
        after_reopen = wait_for_count(server, "/api/projects", before_reopen)
        recovered = page_state(cdp, page)
        recovered_options = recovered.get("picker", {}).get("options") if isinstance(recovered.get("picker"), dict) else None
        if after_reopen <= before_reopen or not entry_has_status(recovered_options, "sleepy", True):
            failures.append(failure(
                "reopened picker to show sleepy available after its database appears",
                {"requests": after_reopen, "before": before_reopen, "entries": recovered_options},
                "browser picker recovery refresh",
            ))
        picker_select(cdp, page, "sleepy")
        recovered_session = wait_for_text(cdp, page, "SLEEPY SESSION")
        if recovered_session.get("hash") != "#/sleepy/" or "SLEEPY SESSION" not in str(recovered_session.get("main", "")):
            failures.append(failure("newly available sleepy sessions without restarting the server", recovered_session, "browser unavailable-project recovery"))

        # Both an unknown project route and a former one-segment session route
        # are project routes now. Neither may retain a prior project's cards.
        for route, request_path in [
            ("#/not-configured/", "/api/projects/not-configured/sessions"),
            ("#/legacy-session-only", "/api/projects/legacy-session-only/sessions"),
        ]:
            evaluate(cdp, page, f"location.hash = {json.dumps(route)}")
            unknown = wait_for_text(cdp, page, "404")
            main = str(unknown.get("main", ""))
            if server.count(request_path) < 1:
                failures.append(failure("a scoped request treating the route segment as a project", server.entries(), f"browser unknown route {route}"))
            if not re.search(r"\\bunknown(?: project)?\\b|not[ -]?found", main, re.I):
                failures.append(failure("a clear unknown-project outcome", main, f"browser unknown route {route}"))
            if unknown.get("picker") is None:
                failures.append(failure("access to the project picker on an unknown-project outcome", unknown.get("header"), f"browser unknown route {route}"))
            if any(label in main for label in ["ALPHA SESSION", "BETA SESSION", "SLEEPY SESSION"]):
                failures.append(failure("no unrelated prior project sessions on an unknown route", main, f"browser unknown route {route}"))

        # A distinct one-project page retains the existing plain breadcrumb and
        # has no picker control at all.
        server.mode = "single"
        single_target, single_page = create_page(cdp, f"{base}/#/")
        targets.append(single_target)
        single = wait_for_text(cdp, single_page, "SOLO SESSION")
        if single.get("hash") != "#/solo/" or "SOLO SESSION" not in str(single.get("main", "")):
            failures.append(failure("single-project root to load solo sessions at #/solo/", single, "browser single-project root"))
        if single.get("picker") is not None or "solo" not in str(single.get("header", "")).lower():
            failures.append(failure("plain solo project navigation with no picker control", {"header": single.get("header"), "picker": single.get("picker")}, "browser single-project navigation"))
    except Exception as error:
        failures.append(failure("project-picker browser criterion to complete without an exception", error, "temporary Chrome browser test"))
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
                chrome.wait(timeout=2)
            except Exception:
                try:
                    chrome.kill()
                except Exception:
                    pass
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def main() -> int:
    failures: list[str] = []
    try:
        if not VISUALIZER.is_dir():
            print(failure("visualizer project directory", "missing", "apps/visualizer"))
            return 1
        modules = frontend_modules()
        if modules is None:
            print(failure("an existing local Vue/Vite toolchain", "no visualizer node_modules with vite and vue-tsc", "apps/visualizer"))
            return 1

        with tempfile.TemporaryDirectory(prefix="mill-picker-criterion-") as directory:
            temp = Path(directory)
            copied = temp / "visualizer"
            shutil.copytree(VISUALIZER, copied, ignore=shutil.ignore_patterns("node_modules", "dist"))
            os.symlink(modules, copied / "node_modules", target_is_directory=True)
            output = temp / "production-build"
            built = subprocess.run(
                ["bun", "run", "build", "--", "--outDir", str(output)],
                cwd=copied,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=25,
                check=False,
            )
            if built.returncode != 0 or not (output / "index.html").is_file():
                failures.append(failure(
                    "a production visualizer build with index.html",
                    f"exit {built.returncode}: {compact(built.stderr or built.stdout)}",
                    "apps/visualizer build",
                ))
            else:
                browser_checks(temp, output, failures)

        if failures:
            for item in failures:
                print(item)
            return 1
        return 0
    except subprocess.TimeoutExpired:
        print(failure("criterion to finish within 55 seconds", "timeout", "tests/acceptance/05-project-picker-and-unavailable-recovery_test.py"))
        return 1
    except Exception as error:
        print(failure("criterion execution without an exception", error, "tests/acceptance/05-project-picker-and-unavailable-recovery_test.py"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
