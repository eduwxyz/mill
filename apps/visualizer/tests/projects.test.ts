import { test, expect } from "bun:test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveDbPath } from "../server/db.ts";
import { resolveProjects } from "../server/projects.ts";

test("legacy --db paths are returned byte-for-byte", () => {
  expect(resolveDbPath([
    "bun",
    "server/index.ts",
    "--db",
    "/private/var/tmp/mill.db",
  ])).toBe("/private/var/tmp/mill.db");
});

test("rejects an explicitly null default instead of selecting the first project", () => {
  const directory = mkdtempSync(join(tmpdir(), "mill-project-config-"));
  const file = join(directory, "projects.json");
  writeFileSync(file, JSON.stringify({
    default: null,
    projects: [{ name: "first", db: "first.db" }],
  }));

  expect(() => resolveProjects(["bun", "server/index.ts", "--projects", file])).toThrow(
    /default.*project/i,
  );
});
