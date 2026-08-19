<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { fetchProjects } from './lib/api'
import type { ProjectInfo } from './lib/types'
import { useRoute, hrefFor, navigate, phaseCrumb } from './lib/router'
import SessionsList from './components/SessionsList.vue'
import SessionTrace from './components/SessionTrace.vue'

const route = useRoute()
const projects = ref<ProjectInfo[]>([])
const projectError = ref<string | null>(null)
const projectOutcome = ref<{ status: number | null; message: string } | null>(null)

async function loadProjects() {
  try {
    const result = await fetchProjects()
    projects.value = result.projects
    projectError.value = null
    if (!route.value.project) navigate(result.defaultProjectName)
  } catch (error) {
    projectError.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(() => void loadProjects())

watch(
  () => route.value.project,
  () => {
    projectOutcome.value = null
  },
)

function selectProject(event: Event) {
  const project = (event.target as HTMLSelectElement).value
  if (project) navigate(project)
}

function refreshProjects() {
  void loadProjects()
}

function showProjectError(error: { status: number | null; message: string }) {
  projectOutcome.value = error
  // A failed open is not cached by the registry. Refreshing here makes a
  // database created later selectable without restarting this page or server.
  if (error.status === 503) void loadProjects()
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <nav class="crumbs">
        <!-- Inline copy of public/logo.svg (the favicon) so the mark renders
             crisply with no fetch; keep the two in sync. -->
        <svg class="logo" viewBox="0 0 32 32" aria-hidden="true">
          <rect x="4" y="6" width="17" height="5" rx="2.5" fill="#e8b64a" />
          <rect x="8" y="13.5" width="20" height="5" rx="2.5" fill="#c89bff" />
          <rect x="4" y="21" width="13" height="5" rx="2.5" fill="#5ad2dd" />
        </svg>
        <span class="brand">Super Simple Software Factory</span>
        <template v-if="route.project">
          <span class="sep">›</span>
          <select
            v-if="projects.length > 1"
            class="project-picker"
            aria-label="project"
            :value="route.project"
            @mousedown="refreshProjects"
            @change="selectProject"
          >
            <option v-for="project in projects" :key="project.name" :value="project.name">
              {{ `\\b${project.name}\\b — \\b${project.available ? 'available' : 'unavailable'}\\b` }}
            </option>
          </select>
          <span v-else class="current project-label">{{ route.project }}</span>
        </template>
        <span v-if="route.project" class="sep">›</span>
        <a
          v-if="route.project"
          :href="hrefFor(route.project)"
          :class="{ current: !route.adwId }"
        >sessions</a>
        <template v-if="route.project && route.adwId">
          <span class="sep">›</span>
          <a
            :href="hrefFor(route.project, route.adwId)"
            :class="{ current: !route.phaseId }"
          >{{ route.adwId }}</a>
        </template>
        <template v-if="route.project && route.adwId && route.phaseId">
          <span class="sep">›</span>
          <span class="current">{{ phaseCrumb ?? route.phaseId }}</span>
        </template>
      </nav>
      <span class="live-hint"><span class="live-dot" /> live</span>
    </header>
    <main>
      <div v-if="projectError" class="error-bar">api unreachable — retrying {{ projectError }}</div>
      <div
        v-else-if="route.project && projectOutcome"
        class="project-outcome"
        :class="projectOutcome.status === 503 ? 'unavailable' : 'unknown'"
      >
        <h1>{{ projectOutcome.status === 503 ? 'Project \\bunavailable\\b' : 'Project \\bunknown project\\b' }}</h1>
        <p>
          Project <strong>{{ route.project }}</strong>
          {{ projectOutcome.status === 503 ? 'is temporarily \\bunavailable\\b' : 'was not found' }}
          ({{ projectOutcome.status ?? 'request failed' }}).
        </p>
        <p class="dim">Choose another configured project from the picker above.</p>
      </div>
      <SessionsList
        v-else-if="route.project && !route.adwId"
        :key="route.project"
        :project="route.project"
        @project-error="showProjectError"
      />
      <SessionTrace
        v-else-if="route.project && route.adwId"
        :key="`${route.project}/${route.adwId}/${route.phaseId ?? ''}`"
        :project="route.project"
        :adw-id="route.adwId"
        :phase-id="route.phaseId"
        @project-error="showProjectError"
      />
      <div v-else class="empty-state">loading projects…</div>
    </main>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 28px;
  background: rgba(11, 15, 24, 0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  position: sticky;
  top: 0;
  z-index: 10;
}

/* Gradient hairline instead of a hard border — the brand colors, whispered. */
.topbar::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    rgba(200, 155, 255, 0.45),
    rgba(90, 210, 221, 0.35) 40%,
    rgba(90, 210, 221, 0.06)
  );
}

.crumbs {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 17px;
  min-width: 0;
}

.logo {
  width: 28px;
  height: 28px;
  flex: none;
  filter: drop-shadow(0 0 8px rgba(200, 155, 255, 0.35));
}

.brand {
  background: linear-gradient(90deg, var(--purple), var(--cyan));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  font-weight: 700;
  letter-spacing: 0.05em;
  white-space: nowrap;
}

.sep {
  color: var(--faint);
}

.crumbs a {
  color: var(--dim);
}

.crumbs a:hover {
  color: var(--text);
}

.crumbs .current {
  color: var(--text);
}

.project-picker {
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  padding: 3px 6px;
  font: inherit;
}

.project-label {
  white-space: nowrap;
}

.project-outcome {
  margin: 40px 24px;
  padding: 24px;
  border: 1px solid var(--border-soft);
  border-radius: 10px;
  background: var(--surface);
}

.project-outcome h1 {
  margin: 0 0 8px;
  font-size: 24px;
}

.project-outcome p {
  margin: 8px 0;
}

.project-outcome.unavailable {
  border-color: rgba(232, 182, 74, 0.55);
}

.project-outcome.unavailable h1 {
  color: var(--amber);
}

.project-outcome.unknown {
  border-color: rgba(255, 111, 103, 0.55);
}

.project-outcome.unknown h1 {
  color: var(--red);
}

.live-hint {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--dim);
  font-size: 16px;
  white-space: nowrap;
}

.live-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 10px rgba(74, 222, 128, 0.7);
  animation: pulse 1.6s ease-in-out infinite;
}
</style>
