"""What this repository's own tooling makes obvious, so nobody has to declare it.

An engineer should not have to write down the test command of a project that
already announces it — `package.json` names its runner, `Cargo.toml` implies
`cargo test`, a `tests/` directory of `*_test.py` implies unittest discovery.

**Detection never invents a passing check.** Whatever it cannot recognise stays
a placeholder, and a placeholder makes the run refuse to start. Silence here
would be the dangerous outcome: a project with no detected checks and no
complaint is a project building on nothing.

`test` is therefore mandatory and the others are opportunistic. Every project
can have tests; not every project has a type checker or a build step, and
demanding one it does not have would only teach the engineer to pass
`--no-checks`.
"""

from __future__ import annotations

import json
from pathlib import Path

MANDATORY = ("test",)


def _json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _has_test_files(root: Path, patterns: tuple[str, ...], depth: int = 3) -> bool:
    """Any matching test file within `depth` levels, ignoring the usual noise."""
    # `adws` is here because THE FACTORY IS NOT THE PROJECT. Without this line, a
    # freshly installed, empty repo "detected" unittest — the `adw_build_test.py`
    # and `adw_plan_build_test.py` scripts match `*_test.py`, and the factory
    # ended up testing itself instead of the engineer's code.
    skip = {"adws", "node_modules", ".git", ".venv", "dist", "build", "__pycache__"}
    for pattern in patterns:
        for found in root.rglob(pattern):
            parts = found.relative_to(root).parts
            if any(part in skip or part.startswith(".") for part in parts[:-1]):
                continue
            if len(parts) <= depth:
                return True
    return False


def detect_checks(repo_root: str | Path) -> dict[str, list[str]]:
    """`{"test": ["bun", "test"], "typecheck": [...]}` — only what is evident."""
    root = Path(repo_root)
    has = lambda name: (root / name).exists()
    found: dict[str, list[str]] = {}

    # ── javascript / typescript ──
    if has("package.json"):
        pkg = _json(root / "package.json")
        scripts = pkg.get("scripts") or {}
        # The lockfile is the strongest signal, but not the only one: a new
        # project has not installed a single dependency yet and still declares
        # itself — `"start": "bun run server.ts"` leaves no doubt about the
        # runtime. Without this, a greenfield repo with tests ended up with no
        # check at all, exactly when the safety net matters most.
        is_bun = (has("bun.lock") or has("bun.lockb")
                  or any(str(v).strip().startswith("bun ") for v in scripts.values()))
        runner = ("bun" if is_bun else "pnpm" if has("pnpm-lock.yaml")
                  else "yarn" if has("yarn.lock") else "npm")

        if scripts.get("test"):
            found["test"] = ["npm", "test"] if runner == "npm" else [runner, "run", "test"]
        elif is_bun and _has_test_files(root, ("*.test.ts", "*.test.tsx", "*.test.js")):
            found["test"] = ["bun", "test"]

        if has("tsconfig.json"):
            found["typecheck"] = ["bunx" if is_bun else "npx", "tsc", "--noEmit"]
        for name, script in (("lint", "lint"), ("build", "build")):
            if scripts.get(script):
                found[name] = ["npm", "run", script] if runner == "npm" else [runner, "run", script]
        return found

    # ── other ecosystems: the project file already states the command ──
    if has("Cargo.toml"):
        return {"test": ["cargo", "test"], "build": ["cargo", "build"]}
    if has("go.mod"):
        return {"test": ["go", "test", "./..."], "build": ["go", "build", "./..."]}
    if has("mix.exs"):
        return {"test": ["mix", "test"]}

    # ── python ──
    if has("pyproject.toml") or has("pytest.ini") or has("setup.cfg"):
        found["test"] = ["pytest", "-q"]
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace") \
            if has("pyproject.toml") else ""
        if "ruff" in pyproject:
            found["lint"] = ["ruff", "check", "."]
        return found
    if _has_test_files(root, ("*_test.py", "test_*.py")):
        # unittest is in the standard library: nothing to install, and the file
        # naming pattern is what says which discovery mode to use.
        pattern = "*_test.py" if _has_test_files(root, ("*_test.py",)) else "test_*.py"
        return {"test": ["python3", "-m", "unittest", "discover", "-s", ".", "-p", pattern]}

    return found


def missing_mandatory(detected: dict[str, list[str]]) -> list[str]:
    """The checks that must exist and were not recognised."""
    return [name for name in MANDATORY if name not in detected]
