import type {
  Envelope,
  EventRow,
  EventsPage,
  GateResult,
  HealthResponse,
  PromptsResponse,
  ProjectsResponse,
  SessionDetail,
  SessionSummary,
} from './types'

async function getJson(url: string): Promise<unknown> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET ${url} → ${res.status}`)
  return res.json()
}

function projectPath(project: string): string {
  return `/api/projects/${encodeURIComponent(project)}`
}

export function fetchProjects(): Promise<ProjectsResponse> {
  return getJson('/api/projects') as Promise<ProjectsResponse>
}

export function fetchSessions(project: string): Promise<SessionSummary[]> {
  return getJson(`${projectPath(project)}/sessions`) as Promise<SessionSummary[]>
}

export async function fetchSession(project: string, adwId: string): Promise<SessionDetail> {
  const detail = (await getJson(
    `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}`,
  )) as SessionDetail
  return {
    session: detail.session,
    usage: detail.usage ?? { read: 0, written: 0 },
    phases: detail.phases ?? [],
    agents: detail.agents ?? [],
  }
}

export async function fetchEvents(
  project: string,
  adwId: string,
  after: number,
  limit = 500,
): Promise<EventsPage> {
  const page = (await getJson(
    `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}/events?after=${after}&limit=${limit}`,
  )) as EventsPage | EventRow[]
  if (Array.isArray(page)) {
    const cursor = page.reduce((max, e) => Math.max(max, e.rowid), after)
    return { events: page, cursor, has_more: page.length === limit }
  }
  return { events: page.events ?? [], cursor: page.cursor ?? after, has_more: page.has_more ?? false }
}

/** Archive a run out of the review list (or restore it with archived=false). */
export async function archiveSession(
  project: string,
  adwId: string,
  archived = true,
): Promise<void> {
  const url = `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}/archive`
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ archived }),
  })
  if (!res.ok) throw new Error(`POST ${url} → ${res.status}`)
}

export function fetchHealth(project: string): Promise<HealthResponse> {
  return getJson(`${projectPath(project)}/health`) as Promise<HealthResponse>
}

// PhaseDetail imports the prompts type from here alongside fetchPrompts.
export type { PromptsResponse }

export async function fetchPrompts(
  project: string,
  adwId: string,
  agent: string,
): Promise<PromptsResponse> {
  const url = `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}/agents/${encodeURIComponent(agent)}/prompts`
  const res = await fetch(url)
  // Not recorded (or endpoint not deployed yet) renders as "no prompts", not an error.
  if (res.status === 404) return { system: null, user: null }
  if (!res.ok) throw new Error(`GET prompts → ${res.status}`)
  const data = (await res.json()) as Partial<PromptsResponse>
  return { system: data.system ?? null, user: data.user ?? null }
}

export function fetchEnvelopes(project: string, adwId: string): Promise<Envelope[]> {
  return getJson(
    `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}/envelopes`,
  ) as Promise<Envelope[]>
}

export function fetchGates(project: string, adwId: string): Promise<GateResult[]> {
  return getJson(
    `${projectPath(project)}/sessions/${encodeURIComponent(adwId)}/gates`,
  ) as Promise<GateResult[]>
}
