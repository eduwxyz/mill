import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { MillDb, resolveDbPath } from "./db.ts";

const DEFAULT_DB_RELATIVE = "adws/adw_data/mill.db";
const SAFE_PROJECT_NAME = /^[A-Za-z0-9._-]+$/;

type JsonRecord = Record<string, unknown>;

type ProjectLocation = "db" | "repo";

export type ResolvedProject = {
  name: string;
  location: string;
};

export type ProjectResolution = {
  projects: ResolvedProject[];
  defaultProjectName: string;
};

export class ProjectConfigurationError extends Error {
  constructor(message: string) {
    super(`Project configuration error: ${message}`);
    this.name = "ProjectConfigurationError";
  }
}

function isRecord(value: unknown): value is JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function expandHome(value: string): string {
  if (value === "~") return homedir();
  if (value.startsWith("~/")) return join(homedir(), value.slice(2));
  return value;
}

function pathFromConfig(value: string, configDir: string): string {
  const expanded = expandHome(value);
  return isAbsolute(expanded) ? expanded : resolve(configDir, expanded);
}

function optionValue(argv: string[], option: string): string | undefined {
  const index = argv.indexOf(option);
  const inline = argv.find((arg) => arg.startsWith(`${option}=`));
  if (index !== -1) {
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new ProjectConfigurationError(`${option} requires a configuration file path`);
    }
    return value;
  }
  return inline?.slice(option.length + 1);
}

function selectedConfigurationPath(argv: string[]): string | undefined {
  // The command line is intentionally checked before the environment. This
  // also means a bad environment path cannot shadow an explicit selection.
  return optionValue(argv, "--projects") ?? process.env.MILL_PROJECTS_CONFIG;
}

function readConfiguration(path: string): { value: JsonRecord; file: string } {
  const file = pathFromConfig(path, process.cwd());
  let text: string;
  try {
    text = readFileSync(file, "utf8");
  } catch (error) {
    throw new ProjectConfigurationError(
      `cannot read ${file}: ${(error as Error).message}`,
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new ProjectConfigurationError(
      `cannot parse JSON in ${file}: ${(error as Error).message}`,
    );
  }
  if (!isRecord(parsed)) {
    throw new ProjectConfigurationError(`${file} must contain a JSON object`);
  }
  return { value: parsed, file };
}

function locationForProject(
  project: JsonRecord,
  index: number,
  configDir: string,
): string {
  const hasDb = Object.prototype.hasOwnProperty.call(project, "db");
  const hasRepo = Object.prototype.hasOwnProperty.call(project, "repo");
  if (hasDb === hasRepo) {
    throw new ProjectConfigurationError(
      `project ${index + 1} must contain exactly one of "db" or "repo"`,
    );
  }

  const key: ProjectLocation = hasDb ? "db" : "repo";
  const raw = project[key];
  if (typeof raw !== "string" || raw.trim() === "") {
    throw new ProjectConfigurationError(
      `project ${index + 1} has an invalid ${key} location; it must be a non-empty string`,
    );
  }
  const base = pathFromConfig(raw, configDir);
  return key === "repo" ? resolve(base, DEFAULT_DB_RELATIVE) : base;
}

function configuredProjects(value: JsonRecord, file: string): ResolvedProject[] {
  if (!Array.isArray(value.projects) || value.projects.length === 0) {
    throw new ProjectConfigurationError(`${file} must define a non-empty "projects" array`);
  }

  const configDir = dirname(file);
  const names = new Set<string>();
  return value.projects.map((item, index) => {
    if (!isRecord(item)) {
      throw new ProjectConfigurationError(`project ${index + 1} must be a JSON object`);
    }
    if (typeof item.name !== "string" || !SAFE_PROJECT_NAME.test(item.name) || item.name === "." || item.name === "..") {
      throw new ProjectConfigurationError(
        `project ${index + 1} has unsafe project name; use a unique URL-safe name`,
      );
    }
    if (names.has(item.name)) {
      throw new ProjectConfigurationError(`duplicate project name "${item.name}"`);
    }
    names.add(item.name);
    return { name: item.name, location: locationForProject(item, index, configDir) };
  });
}

/**
 * Resolve either a JSON project set or the original single-project selector.
 * In the fallback branch resolveDbPath is deliberately returned unchanged:
 * in particular, no realpath or path normalization is applied to legacy paths.
 */
export function resolveProjects(argv: string[] = Bun.argv): ProjectResolution {
  const configPath = selectedConfigurationPath(argv);
  if (configPath !== undefined) {
    const { value, file } = readConfiguration(configPath);
    const projects = configuredProjects(value, file);
    const defaultKeys = ["default", "defaultProject", "defaultProjectName"] as const;
    const defaultKey = defaultKeys.find((key) =>
      Object.prototype.hasOwnProperty.call(value, key),
    );
    const configuredDefault = defaultKey === undefined ? undefined : value[defaultKey];
    if (configuredDefault !== undefined && typeof configuredDefault !== "string") {
      throw new ProjectConfigurationError("the default project must be a project name");
    }
    const defaultProjectName = configuredDefault === undefined
      ? projects[0]!.name
      : configuredDefault;
    if (!projects.some((project) => project.name === defaultProjectName)) {
      throw new ProjectConfigurationError(
        `default project "${defaultProjectName}" is not present in projects`,
      );
    }
    return { projects, defaultProjectName };
  }

  const location = resolveDbPath(argv);
  return {
    projects: [{ name: "default", location }],
    defaultProjectName: "default",
  };
}

export class UnknownProjectError extends Error {
  readonly code = "PROJECT_NOT_FOUND";

  constructor(readonly projectName: string) {
    super(`unknown configured project "${projectName}"`);
    this.name = "UnknownProjectError";
  }
}

export class ProjectUnavailableError extends Error {
  readonly code = "PROJECT_UNAVAILABLE";

  constructor(readonly projectName: string, readonly location: string, cause?: unknown) {
    const reason = cause instanceof Error ? `: ${cause.message}` : "";
    super(
      `configured project "${projectName}" is unavailable; database does not exist at ${location}${reason}`,
      cause ? { cause } : undefined,
    );
    this.name = "ProjectUnavailableError";
  }
}

function projectsFromInput(input: unknown): ResolvedProject[] {
  const candidate = isRecord(input) && isRecord(input.value) ? input.value : input;
  const projects = Array.isArray(candidate)
    ? candidate
    : isRecord(candidate) && Array.isArray(candidate.projects)
      ? candidate.projects
      : [];
  return projects.flatMap((item) => {
    if (!isRecord(item) || typeof item.name !== "string") return [];
    const location = item.location ?? item.dbPath ?? item.databasePath;
    return typeof location === "string" ? [{ name: item.name, location }] : [];
  });
}

/**
 * A lazy registry. Listing only checks file existence; opening happens on get,
 * and failed opens are not cached so a database created later can be retried.
 */
export class ProjectRegistry {
  private readonly projects: ResolvedProject[];
  private readonly openDatabases = new Map<string, MillDb>();
  private readonly availabilityErrors = new Map<string, string>();

  constructor(input: unknown) {
    this.projects = projectsFromInput(input);
    if (this.projects.length === 0) {
      throw new ProjectConfigurationError("registry requires at least one resolved project");
    }
  }

  list(): Array<ResolvedProject & { available: boolean; availabilityError: string | null }> {
    return this.projects.map((project) => ({
      ...project,
      available: existsSync(project.location),
      availabilityError: this.availabilityErrors.get(project.name) ?? null,
    }));
  }

  get(name: string): MillDb {
    const project = this.projects.find((candidate) => candidate.name === name);
    if (!project) {
      throw new UnknownProjectError(name);
    }

    const cached = this.openDatabases.get(name);
    if (cached) return cached;
    if (!existsSync(project.location)) {
      const error = new ProjectUnavailableError(project.name, project.location);
      this.availabilityErrors.set(name, error.message);
      throw error;
    }

    try {
      const database = new MillDb(project.location);
      this.openDatabases.set(name, database);
      this.availabilityErrors.delete(name);
      return database;
    } catch (cause) {
      const error = new ProjectUnavailableError(project.name, project.location, cause);
      this.availabilityErrors.set(name, error.message);
      throw error;
    }
  }

  close(): void {
    for (const database of this.openDatabases.values()) database.close();
    this.openDatabases.clear();
  }
}