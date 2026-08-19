import { ref } from 'vue'

// Hash routes: #/<project>/ → sessions · #/<project>/<adw_id> → waterfall
// · #/<project>/<adw_id>/<phase_id> → phase panel open.
export interface Route {
  project: string | null
  adwId: string | null
  phaseId: string | null
}

function parse(): Route {
  const parts = window.location.hash
    .replace(/^#\/?/, '')
    .split('/')
    .filter(Boolean)
    .map(decodeURIComponent)
  return {
    project: parts[0] ?? null,
    adwId: parts[1] ?? null,
    phaseId: parts[2] ?? null,
  }
}

const route = ref<Route>(parse())

window.addEventListener('hashchange', () => {
  route.value = parse()
})

export function useRoute() {
  return route
}

// Display name for the phase crumb — set by the trace view once phases load,
// since the phase_id in the URL is not the display name.
export const phaseCrumb = ref<string | null>(null)

export function hrefFor(
  project?: string | null,
  adwId?: string | null,
  phaseId?: string | null,
): string {
  let h = '#/'
  if (project) h += `${encodeURIComponent(project)}/`
  if (project && adwId) h += encodeURIComponent(adwId)
  if (project && adwId && phaseId) h += `/${encodeURIComponent(phaseId)}`
  return h
}

export function navigate(
  project?: string | null,
  adwId?: string | null,
  phaseId?: string | null,
): void {
  window.location.hash = hrefFor(project, adwId, phaseId)
}
