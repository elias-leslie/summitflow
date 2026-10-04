import type { DevelopmentProjection, RepoStatus } from '@/lib/api/git'

export const repo: RepoStatus = {
  path: '/repos/alpha',
  name: 'alpha',
  project_id: 'project-alpha',
  branch: 'main',
  uncommitted: 2,
  ahead: 1,
  behind: 0,
  state: 'dirty',
}
export const sourceSha = 'a'.repeat(40)
const missing = {
  state: 'unavailable',
  source_commit: null,
  observed_at: null,
  evidence: null,
  reason: 'No retained evidence',
}
export const development: DevelopmentProjection = {
  version: 'development.v1',
  project_id: 'project-alpha',
  observed_at: '2026-10-03T20:00:00Z',
  working_tree: {
    ...missing,
    state: 'uncommitted',
    source_commit: sourceSha,
    uncommitted: 2,
    unpublished: 1,
  },
  accepted: {
    ...missing,
    state: 'accepted',
    source_commit: sourceSha,
    full_coverage: true,
    reason: 'Full local acceptance',
  },
  running: {
    ...missing,
    state: 'observed',
    source_commit: 'b'.repeat(40),
    drift: true,
    reason: 'Recorded runtime observation',
  },
  recovery: {
    capture: missing,
    offsite: missing,
    snapshot: missing,
    restore: missing,
  },
  publication: missing,
  blockers: { state: 'available', items: [] },
}
