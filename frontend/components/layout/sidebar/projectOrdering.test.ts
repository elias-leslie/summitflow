import { describe, expect, it } from 'vitest'
import type { Project } from '@/lib/api'
import {
  groupProjectsForSidebar,
  reorderProjectsWithinCategory,
  sortProjectsForSidebar,
} from './projectOrdering'

function buildProject(overrides: Partial<Project>): Project {
  return {
    id: 'project',
    name: 'Project',
    base_url: 'https://example.com',
    health_endpoint: '/health',
    category: 'dev',
    sidebar_rank: null,
    created_at: '2026-04-01T00:00:00Z',
    ...overrides,
  }
}

describe('projectOrdering', () => {
  it('sorts by category, sidebar rank, then name', () => {
    const projects = [
      buildProject({ id: 'dev-zulu', name: 'Zulu', category: 'dev' }),
      buildProject({ id: 'prod-alpha', name: 'Alpha', category: 'production' }),
      buildProject({ id: 'testing-delta', name: 'Delta', category: 'testing' }),
      buildProject({
        id: 'prod-bravo',
        name: 'Bravo',
        category: 'production',
        sidebar_rank: 0,
      }),
      buildProject({
        id: 'testing-charlie',
        name: 'Charlie',
        category: 'testing',
        sidebar_rank: 1,
      }),
    ]

    expect(
      sortProjectsForSidebar(projects).map((project) => project.id),
    ).toEqual([
      'prod-bravo',
      'prod-alpha',
      'testing-charlie',
      'testing-delta',
      'dev-zulu',
    ])
  })

  it('groups projects by category in sorted order', () => {
    const grouped = groupProjectsForSidebar([
      buildProject({ id: 'dev-b', name: 'Bravo', category: 'dev' }),
      buildProject({ id: 'prod-a', name: 'Alpha', category: 'production' }),
      buildProject({ id: 'testing-c', name: 'Charlie', category: 'testing' }),
    ])

    expect(grouped.production.map((project) => project.id)).toEqual(['prod-a'])
    expect(grouped.testing.map((project) => project.id)).toEqual(['testing-c'])
    expect(grouped.dev.map((project) => project.id)).toEqual(['dev-b'])
  })

  it('reassigns sequential ranks when a category is reordered', () => {
    const projects = [
      buildProject({ id: 'prod-a', name: 'Alpha', category: 'production' }),
      buildProject({ id: 'prod-b', name: 'Bravo', category: 'production' }),
      buildProject({ id: 'prod-c', name: 'Charlie', category: 'production' }),
      buildProject({ id: 'testing-a', name: 'Testing', category: 'testing' }),
    ]

    const result = reorderProjectsWithinCategory(
      projects,
      'production',
      'prod-c',
      'prod-a',
    )

    expect(result).not.toBeNull()
    expect(result?.updates).toEqual([
      { id: 'prod-c', sidebar_rank: 0 },
      { id: 'prod-a', sidebar_rank: 1 },
      { id: 'prod-b', sidebar_rank: 2 },
    ])
    expect(
      result?.projects.map((project) => [project.id, project.sidebar_rank]),
    ).toEqual([
      ['prod-c', 0],
      ['prod-a', 1],
      ['prod-b', 2],
      ['testing-a', null],
    ])
  })
})
