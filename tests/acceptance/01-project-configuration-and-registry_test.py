#!/usr/bin/env python3
"""Acceptance criterion for ticket 01: project configuration and registry."""

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
import { homedir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.env.PROJECT_ROOT!;
const visualizerDir = process.env.VISUALIZER_DIR!;
const testRoot = process.env.ACCEPTANCE_TMP!;
const resultPath = process.env.ACCEPTANCE_RESULT!;
const failures: string[] = [];
const projectEnvKeys = ["MILL_PROJECTS_CONFIG", "MILL_DB"] as const;

type ModuleRecord = { file: string; exports: Record<string, unknown> };
type NormalizedProject = { name: string; location: string; raw: Record<string, unknown> };
type Resolution = {
  raw: unknown;
  projects: NormalizedProject[];
  defaultName: string;
};
type Resolver = {
  name: string;
  invoke: (argv: string[], env: Record<string, string | undefined>, cwd: string) => Promise<unknown>;
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

function errorText(value: unknown): string {
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["error", "message", "reason", "code", "kind", "status"]) {
      if (typeof record[key] === "string" && record[key]) return String(record[key]);
    }
  }
  return compact(value);
}

function serverFiles(dir: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const file = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...serverFiles(file));
    else if (entry.isFile() && entry.name.endsWith(".ts") && entry.name !== "index.ts") files.push(file);
  }
  return files;
}

async function loadServerModules(): Promise<ModuleRecord[]> {
  const modules: ModuleRecord[] = [];
  for (const file of serverFiles(join(visualizerDir, "server"))) {
    try {
      modules.push({
        file,
        exports: await import(pathToFileURL(file).href) as Record<string, unknown>,
      });
    } catch {
      // A module that cannot be imported cannot expose the configuration seam.
    }
  }
  return modules;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function locationOf(value: Record<string, unknown>): string | null {
  for (const key of ["dbPath", "databasePath", "database", "db", "path", "location"]) {
    if (typeof value[key] === "string") return value[key] as string;
  }
  return null;
}

function normalizeResolution(raw: unknown): Resolution {
  const outer = record(raw);
  const value = outer && record(outer.value) && Array.isArray(record(outer.value)!.projects)
    ? record(outer.value)!
    : outer;
  const rawProjects = Array.isArray(value) ? value : value?.projects;
  if (!Array.isArray(rawProjects) || rawProjects.length === 0) {
    throw new Error("resolver did not return a non-empty resolved project list");
  }

  const projects: NormalizedProject[] = rawProjects.map((item, index) => {
    const itemRecord = record(item);
    const name = itemRecord?.name;
    const location = itemRecord ? locationOf(itemRecord) : null;
    if (typeof name !== "string" || !location) {
      throw new Error(`resolved project ${index} has no string name and resolved database location`);
    }
    return { name, location, raw: itemRecord };
  });

  const defaultValue = value?.defaultProjectName ?? value?.defaultProject ?? value?.default;
  const defaultRecord = record(defaultValue);
  const defaultName = typeof defaultValue === "string"
    ? defaultValue
    : typeof defaultRecord?.name === "string"
      ? defaultRecord.name
      : projects[0]!.name;
  return { raw, projects, defaultName };
}

async function withRuntime<T>(
  env: Record<string, string | undefined>,
  cwd: string,
  action: (optionEnv: Record<string, string | undefined>) => Promise<T> | T,
): Promise<T> {
  const previousCwd = process.cwd();
  const previous = new Map<string, string | undefined>();
  for (const key of projectEnvKeys) previous.set(key, process.env[key]);
  try {
    for (const key of projectEnvKeys) {
      const value = env[key];
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    process.chdir(cwd);
    return await action({ ...process.env, ...env });
  } finally {
    process.chdir(previousCwd);
    for (const key of projectEnvKeys) {
      const value = previous.get(key);
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

async function findResolver(modules: ModuleRecord[], configPath: string, cwd: string): Promise<Resolver | null> {
  const argv = ["bun", "server/index.ts", "--projects", configPath];
  const env = { MILL_PROJECTS_CONFIG: undefined, MILL_DB: undefined };

  for (const module of modules) {
    for (const [exportName, exported] of Object.entries(module.exports)) {
      if (typeof exported !== "function") continue;
      const functionValue = exported as (...args: unknown[]) => unknown;
      const attempts: Array<{
        suffix: string;
        call: (args: string[], optionsEnv: Record<string, string | undefined>, callCwd: string) => unknown;
      }> = [
        { suffix: "argv", call: (args) => functionValue(args) },
        {
          suffix: "options",
          call: (args, optionsEnv, callCwd) => functionValue({ argv: args, env: optionsEnv, cwd: callCwd }),
        },
      ];
      for (const attempt of attempts) {
        try {
          const raw = await withRuntime(env, cwd, (optionEnv) =>
            Promise.resolve(attempt.call(argv, optionEnv, cwd)),
          );
          normalizeResolution(raw);
          return {
            name: `${relative(visualizerDir, module.file)}:${exportName} (${attempt.suffix})`,
            invoke: (args, desiredEnv, desiredCwd) => withRuntime(desiredEnv, desiredCwd, (optionEnv) =>
              Promise.resolve(attempt.call(args, optionEnv, desiredCwd)),
            ),
          };
        } catch {
          // This export either is not the selector-aware resolver or needs a
          // different input shape. The behaviour contract is selected below.
        }
      }
    }
  }
  return null;
}

async function resolveProjectSet(
  resolver: Resolver,
  argv: string[],
  env: Record<string, string | undefined>,
  cwd: string,
  at: string,
): Promise<Resolution | null> {
  try {
    return normalizeResolution(await resolver.invoke(argv, env, cwd));
  } catch (error) {
    fail("a resolved non-empty project set", errorText(error), at);
    return null;
  }
}

async function expectConfigurationError(
  resolver: Resolver,
  label: string,
  file: string,
  cwd: string,
  terms: RegExp,
): Promise<void> {
  const argv = ["bun", "server/index.ts", "--projects", file];
  try {
    const returned = await resolver.invoke(argv, { MILL_PROJECTS_CONFIG: undefined, MILL_DB: undefined }, cwd);
    try {
      const normalized = normalizeResolution(returned);
      fail(
        `an actionable configuration error for ${label}`,
        normalized.projects.map((project) => ({ name: project.name, db: project.location })),
        `--projects ${label}`,
      );
    } catch (normalizationError) {
      const message = errorText(returned);
      check(
        message.length > 0 && terms.test(message),
        `an actionable configuration error identifying ${label}`,
        message || errorText(normalizationError),
        `--projects ${label}`,
      );
    }
  } catch (error) {
    const message = errorText(error);
    check(
      message.length > 0 && terms.test(message),
      `an actionable configuration error identifying ${label}`,
      message,
      `--projects ${label}`,
    );
  }
}

function availabilityOf(value: Record<string, unknown>): boolean | null {
  if (typeof value.available === "boolean") return value.available;
  if (typeof value.availability === "boolean") return value.availability;
  if (value.availability === "available") return true;
  if (value.availability === "unavailable") return false;
  return null;
}

function reportedError(value: Record<string, unknown>): unknown {
  return value.error ?? value.availabilityError ?? value.errorMessage;
}

async function getOutcome(registry: Record<string, (...args: never[]) => unknown>, name: string): Promise<{
  ok: boolean;
  value?: unknown;
  text: string;
}> {
  try {
    const value = await (registry.get as (project: string) => unknown)(name);
    const valueRecord = record(value);
    const text = valueRecord
      ? [valueRecord.kind, valueRecord.status, valueRecord.code, valueRecord.error, valueRecord.message]
          .filter((part) => typeof part === "string")
          .join(" ") || compact(value)
      : compact(value);
    const openedPath = databasePathFromGet(value);
    return openedPath ? { ok: true, value, text } : { ok: false, value, text };
  } catch (error) {
    return { ok: false, text: errorText(error) };
  }
}

function databasePathFromGet(value: unknown): string | null {
  const valueRecord = record(value);
  if (!valueRecord) return null;
  if (typeof valueRecord.path === "string") return valueRecord.path;
  for (const key of ["db", "database", "value", "project"]) {
    const nested = record(valueRecord[key]);
    if (nested && typeof nested.path === "string") return nested.path;
  }
  return null;
}

function isUnknownOutcome(outcome: { ok: boolean; text: string }): boolean {
  return !outcome.ok && /\bunknown\b|not[ -]?found project|no (?:configured )?project|not configured/i.test(outcome.text);
}

function isUnavailableOutcome(outcome: { ok: boolean; text: string }, expectedPath: string): boolean {
  return !outcome.ok && (
    /\bunavailable\b|cannot open|no such file|not found|does not exist|\bmissing\b/i.test(outcome.text) ||
    outcome.text.includes(expectedPath)
  );
}

function makeMillDatabase(path: string): void {
  mkdirSync(dirname(path), { recursive: true });
  const db = new Database(path);
  try {
    // This is the real Mill database's sessions table shape, sufficient for a
    // MillDb reader to make a readonly query after the late file is created.
    db.exec(`
      PRAGMA journal_mode=WAL;
      CREATE TABLE sessions (
        adw_id TEXT PRIMARY KEY, adw_name TEXT, request TEXT, status TEXT,
        engineer TEXT, started_at TEXT, ended_at TEXT, total_tokens INTEGER,
        total_cost REAL, archived INTEGER
      );
    `);
  } finally {
    db.close();
  }
}

function markdownFiles(dir: string): string[] {
  const files: string[] = [];
  if (!existsSync(dir)) return files;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === "dist" || entry.name.startsWith(".")) continue;
    const file = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...markdownFiles(file));
    else if (entry.isFile() && entry.name.toLowerCase().endsWith(".md")) files.push(file);
  }
  return files;
}

function documentedConfiguration(text: string): boolean {
  const fencedJson = /```[^\n]*\n([\s\S]*?)```/g;
  for (const match of text.matchAll(fencedJson)) {
    try {
      const value = JSON.parse(match[1]!);
      const config = record(value);
      const projects = config?.projects;
      if (!Array.isArray(projects) || projects.length === 0) continue;
      if (projects.every((project) => {
        const item = record(project);
        const locations = Number(typeof item?.db === "string") + Number(typeof item?.repo === "string");
        return typeof item?.name === "string" && locations === 1;
      })) return true;
    } catch {
      // A configuration example must itself be valid JSON to document the shape.
    }
  }
  return false;
}

async function verifyDocumentation(): Promise<void> {
  const docs = [join(root, "README.md"), ...markdownFiles(visualizerDir)]
    .filter((file, index, all) => all.indexOf(file) === index && existsSync(file));
  const text = (await Promise.all(docs.map((file) => Bun.file(file).text()))).join("\n");
  check(
    documentedConfiguration(text),
    "visualizer documentation with a valid JSON projects example containing name and exactly one db or repo",
    docs.length === 0 ? "no visualizer documentation" : "no valid JSON project configuration example",
    "README.md or apps/visualizer documentation",
  );
  check(
    /--projects(?:\s|=|<)/.test(text) && /MILL_PROJECTS_CONFIG/.test(text),
    "documented --projects and MILL_PROJECTS_CONFIG project-selection invocation",
    text.match(/(?:--projects|MILL_PROJECTS_CONFIG).{0,100}/g) ?? "neither selector documented",
    "README.md or apps/visualizer documentation",
  );
}

async function registryFor(
  modules: ModuleRecord[],
  resolution: Resolution,
): Promise<Record<string, (...args: never[]) => unknown> | null> {
  const rawRecord = record(resolution.raw);
  const candidateInputs: unknown[] = [
    resolution.raw,
    rawRecord ? { projects: rawRecord.projects, defaultProject: rawRecord.defaultProject ?? rawRecord.default } : undefined,
    rawRecord?.projects,
  ].filter((value) => value !== undefined);

  for (const module of modules) {
    for (const [exportName, exported] of Object.entries(module.exports)) {
      if (typeof exported !== "function") continue;
      const prototype = (exported as { prototype?: unknown }).prototype as Record<string, unknown> | undefined;
      for (const input of candidateInputs) {
        const constructors: Array<() => unknown> = [
          () => new (exported as new (value: unknown) => unknown)(input),
          () => (exported as (value: unknown) => unknown)(input),
        ];
        for (const construct of constructors) {
          try {
            const instance = await Promise.resolve(construct());
            const registry = record(instance) as Record<string, (...args: never[]) => unknown> | null;
            if (
              registry && typeof registry.list === "function" && typeof registry.get === "function" &&
              typeof registry.close === "function"
            ) return registry;
            try { (registry?.close as (() => void) | undefined)?.(); } catch {}
          } catch {
            // Keep looking: factories and constructors legitimately have
            // different input shapes, but a usable registry exposes all three
            // public operations and is exercised below.
          }
        }
      }
    }
  }
  return null;
}

test("configured project resolution and retryable availability", async () => {
  const registries: Array<Record<string, (...args: never[]) => unknown>> = [];
  try {
    const configDir = join(testRoot, "configs", "nested");
    const launchDir = join(testRoot, "launch");
    mkdirSync(configDir, { recursive: true });
    mkdirSync(launchDir, { recursive: true });

    const selectedConfig = join(configDir, "selected.json");
    const environmentConfig = join(configDir, "environment.json");
    const noDefaultConfig = join(configDir, "first-default.json");
    writeFileSync(selectedConfig, JSON.stringify({
      default: "repo.project",
      projects: [
        { name: "db-project", db: "relative/data/alpha.db" },
        { name: "repo.project", repo: "relative/repositories/beta" },
        { name: "home_project", db: "~/mill-project-criterion-home.db" },
      ],
    }), "utf8");
    writeFileSync(environmentConfig, JSON.stringify({
      default: "from-environment",
      projects: [{ name: "from-environment", db: "environment.db" }],
    }), "utf8");
    writeFileSync(noDefaultConfig, JSON.stringify({
      projects: [
        { name: "first-project", db: "first.db" },
        { name: "second-project", db: "second.db" },
      ],
    }), "utf8");

    const modules = await loadServerModules();
    const resolver = await findResolver(modules, selectedConfig, launchDir);
    if (!resolver) {
      fail(
        "a selector-aware project resolver that turns --projects JSON into resolved projects",
        "no importable server export accepted --projects and returned project names with database locations",
        "apps/visualizer/server",
      );
      await verifyDocumentation();
      return;
    }

    const selected = await resolveProjectSet(
      resolver,
      ["bun", "server/index.ts", "--projects", selectedConfig],
      { MILL_PROJECTS_CONFIG: environmentConfig, MILL_DB: "/private/ignored-by-project-config/mill.db" },
      launchDir,
      `configured selection via ${resolver.name}`,
    );
    if (selected) {
      check(
        selected.projects.map((project) => project.name).join("|") === "db-project|repo.project|home_project",
        "configured project names in JSON order",
        selected.projects.map((project) => project.name),
        "--projects selected configuration",
      );
      check(
        selected.projects.map((project) => project.location).join("|") === [
          resolve(configDir, "relative/data/alpha.db"),
          resolve(configDir, "relative/repositories/beta/adws/adw_data/mill.db"),
          resolve(homedir(), "mill-project-criterion-home.db"),
        ].join("|"),
        "db paths relative to the configuration, repo paths under adws/adw_data/mill.db, and expanded home paths",
        selected.projects.map((project) => project.location),
        "resolved configured project locations",
      );
      check(
        selected.defaultName === "repo.project",
        "explicit default repo.project",
        selected.defaultName,
        "configured default project",
      );
    }

    const environmentSelected = await resolveProjectSet(
      resolver,
      ["bun", "server/index.ts"],
      { MILL_PROJECTS_CONFIG: environmentConfig, MILL_DB: undefined },
      launchDir,
      "MILL_PROJECTS_CONFIG selection",
    );
    if (environmentSelected) {
      check(
        environmentSelected.projects.length === 1 && environmentSelected.projects[0]!.name === "from-environment",
        "MILL_PROJECTS_CONFIG project set when --projects is absent",
        environmentSelected.projects.map((project) => project.name),
        "MILL_PROJECTS_CONFIG selection",
      );
    }

    const firstDefault = await resolveProjectSet(
      resolver,
      ["bun", "server/index.ts", "--projects", noDefaultConfig],
      { MILL_PROJECTS_CONFIG: undefined, MILL_DB: undefined },
      launchDir,
      "implicit first configured default",
    );
    if (firstDefault) {
      check(
        firstDefault.defaultName === "first-project",
        "first-project as the default when JSON has no default",
        firstDefault.defaultName,
        "configuration without default",
      );
    }

    const invalidCases: Array<{ label: string; text: string; terms: RegExp }> = [
      { label: "malformed JSON", text: "{", terms: /json|parse|invalid/i },
      { label: "empty project list", text: JSON.stringify({ projects: [] }), terms: /empty|project/i },
      {
        label: "unsafe project name",
        text: JSON.stringify({ projects: [{ name: "../escape", db: "escape.db" }] }),
        terms: /name|safe|url|segment/i,
      },
      {
        label: "unsafe whitespace project name",
        text: JSON.stringify({ projects: [{ name: "not url safe", db: "escape.db" }] }),
        terms: /name|safe|url|segment/i,
      },
      {
        label: "unsafe dot project name",
        text: JSON.stringify({ projects: [{ name: ".", db: "escape.db" }] }),
        terms: /name|safe|url|segment/i,
      },
      {
        label: "duplicate project names",
        text: JSON.stringify({ projects: [{ name: "same", db: "one.db" }, { name: "same", db: "two.db" }] }),
        terms: /duplicate|unique|name/i,
      },
      {
        label: "invalid default",
        text: JSON.stringify({ default: "missing", projects: [{ name: "present", db: "present.db" }] }),
        terms: /default|missing|project/i,
      },
      {
        label: "both db and repo",
        text: JSON.stringify({ projects: [{ name: "both", db: "one.db", repo: "repo" }] }),
        terms: /db|repo|exactly|location/i,
      },
      {
        label: "neither db nor repo",
        text: JSON.stringify({ projects: [{ name: "neither" }] }),
        terms: /db|repo|exactly|location/i,
      },
    ];
    for (const invalid of invalidCases) {
      const file = join(configDir, `${invalid.label.replace(/\W+/g, "-")}.json`);
      writeFileSync(file, invalid.text, "utf8");
      await expectConfigurationError(resolver, invalid.label, file, launchDir, invalid.terms);
    }

    const dbModule = modules.find((module) => typeof module.exports.resolveDbPath === "function");
    const legacyResolver = dbModule?.exports.resolveDbPath as ((argv: string[]) => string) | undefined;
    if (!legacyResolver) {
      fail(
        "the existing resolveDbPath legacy resolver used as the byte-for-byte baseline",
        "no importable resolveDbPath export",
        "apps/visualizer/server",
      );
    } else {
      const legacyCases: Array<{
        label: string;
        argv: string[];
        env: Record<string, string | undefined>;
      }> = [
        {
          label: "--db over MILL_DB",
          argv: ["bun", "server/index.ts", "--db", "cli-choice/mill.db"],
          env: { MILL_PROJECTS_CONFIG: undefined, MILL_DB: "/private/ignored-by-cli/mill.db" },
        },
        {
          label: "MILL_DB /private path",
          argv: ["bun", "server/index.ts"],
          env: { MILL_PROJECTS_CONFIG: undefined, MILL_DB: "/private/var/folders/mill-criterion/legacy.db" },
        },
        {
          label: "working-directory fallback",
          argv: ["bun", "server/index.ts"],
          env: { MILL_PROJECTS_CONFIG: undefined, MILL_DB: undefined },
        },
      ];
      for (const legacy of legacyCases) {
        const expected = await withRuntime(legacy.env, launchDir, () => legacyResolver(legacy.argv));
        const actual = await resolveProjectSet(resolver, legacy.argv, legacy.env, launchDir, `legacy ${legacy.label}`);
        if (!actual) continue;
        check(
          actual.projects.length === 1,
          "one legacy project when no project configuration is selected",
          actual.projects.map((project) => project.name),
          `legacy ${legacy.label}`,
        );
        check(
          actual.projects[0]?.location === expected,
          `legacy database path byte-for-byte equal to resolveDbPath for ${legacy.label}`,
          actual.projects[0]?.location,
          `legacy ${legacy.label}`,
        );
      }
    }

    const registryConfig = join(configDir, "registry.json");
    const latePath = resolve(configDir, "late/adws/adw_data/mill.db");
    const opaquePath = resolve(configDir, "opaque.db");
    mkdirSync(dirname(opaquePath), { recursive: true });
    writeFileSync(opaquePath, "", "utf8");
    writeFileSync(registryConfig, JSON.stringify({
      projects: [
        { name: "late-project", repo: "late" },
        { name: "opaque-project", db: "opaque.db" },
      ],
    }), "utf8");
    const registryResolution = await resolveProjectSet(
      resolver,
      ["bun", "server/index.ts", "--projects", registryConfig],
      { MILL_PROJECTS_CONFIG: undefined, MILL_DB: undefined },
      launchDir,
      "registry configuration",
    );
    if (registryResolution) {
      const registry = await registryFor(modules, registryResolution);
      if (!registry) {
        fail(
          "a project registry whose list, get, and close operations work for resolved projects",
          "no registry could be constructed from the resolved configuration",
          "apps/visualizer/server",
        );
      } else {
        registries.push(registry);
        const initialList = await (registry.list as () => unknown)();
        if (!Array.isArray(initialList)) {
          fail("a list of configured project availability records", initialList, "ProjectRegistry.list()");
        } else {
          const records = initialList.map(record);
          const late = records.find((item) => item?.name === "late-project") ?? null;
          const opaque = records.find((item) => item?.name === "opaque-project") ?? null;
          check(
            records.filter(Boolean).length === 2 && !!late && !!opaque,
            "both configured project names in registry list",
            initialList,
            "ProjectRegistry.list() before opening databases",
          );
          check(
            locationOf(late ?? {}) === latePath && locationOf(opaque ?? {}) === opaquePath,
            "resolved configured database locations in registry list",
            initialList,
            "ProjectRegistry.list() locations",
          );
          check(
            availabilityOf(late ?? {}) === false && availabilityOf(opaque ?? {}) === true,
            "file-based availability false for missing late database and true for existing opaque file",
            initialList,
            "ProjectRegistry.list() file availability",
          );
          check(
            reportedError(opaque ?? {}) === undefined || reportedError(opaque ?? {}) === null || reportedError(opaque ?? {}) === "",
            "no database-open error for existing opaque file before any get request",
            reportedError(opaque ?? {}),
            "ProjectRegistry.list() must not open databases",
          );
        }

        const unknown = await getOutcome(registry, "not-configured");
        const unavailable = await getOutcome(registry, "late-project");
        check(
          isUnknownOutcome(unknown),
          "an unknown-project outcome distinct from configured availability failures",
          unknown.text,
          "ProjectRegistry.get(not-configured)",
        );
        check(
          isUnavailableOutcome(unavailable, latePath),
          "a configured-but-unavailable database outcome",
          unavailable.text,
          "ProjectRegistry.get(late-project) before database exists",
        );
        check(
          unknown.text !== unavailable.text,
          "different unknown-project and unavailable-project outcomes",
          { unknown: unknown.text, unavailable: unavailable.text },
          "ProjectRegistry.get() outcome distinction",
        );

        makeMillDatabase(latePath);
        const afterCreation = await (registry.list as () => unknown)();
        const createdRecord = Array.isArray(afterCreation)
          ? afterCreation.map(record).find((item) => item?.name === "late-project") ?? null
          : null;
        check(
          availabilityOf(createdRecord ?? {}) === true,
          "available late-project after its database file is created",
          createdRecord ?? afterCreation,
          "ProjectRegistry.list() after late database creation",
        );
        const retried = await getOutcome(registry, "late-project");
        const retriedPath = retried.ok ? databasePathFromGet(retried.value) : null;
        check(
          retried.ok && retriedPath === latePath,
          "a later get to open the database created after the first unavailable failure",
          retried.ok ? retriedPath : retried.text,
          "ProjectRegistry.get(late-project) retry",
        );
      }
    }

    await verifyDocumentation();
  } catch (error) {
    fail(
      "configured-project Bun criterion to complete without an exception",
      errorText(error),
      "temporary Bun test",
    );
  } finally {
    for (const registry of registries) {
      try { await (registry.close as () => unknown)(); } catch {}
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

        with tempfile.TemporaryDirectory(prefix="mill-project-registry-criterion-") as temp_dir:
            temp = Path(temp_dir)
            test_path = temp / "project_configuration_registry.test.ts"
            result_path = temp / "result.json"
            test_path.write_text(BUN_TEST, encoding="utf-8")
            env = os.environ.copy()
            env.update(
                {
                    "PROJECT_ROOT": str(ROOT),
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
                            "expected a list of focused Bun test failures, "
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
                    "expected focused Bun project configuration test to exit 0, "
                    f"found exit {completed.returncode}, at temporary Bun test"
                )
                return 1
            return 0
    except subprocess.TimeoutExpired:
        print("expected criterion to finish within 45 seconds, found timeout, at temporary Bun test")
        return 1
    except Exception as error:  # Criterion contract: readable error, no traceback.
        print(
            "expected criterion execution without an exception, "
            f"found {single_line(error)}, at tests/acceptance/01-project-configuration-and-registry_test.py"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
