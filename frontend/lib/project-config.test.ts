import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PROJECT_ID,
  getProjectIdFromPathname,
  getProjectIdOrDefault,
  getProjectMemoryGroupPrefix,
  getRouteProjectId,
} from './project-config'

describe('project-config', () => {
  it('ignores reserved project route ids', () => {
    expect(getRouteProjectId('new')).toBeNull()
    expect(getProjectIdOrDefault('new')).toBe(DEFAULT_PROJECT_ID)
    expect(getProjectMemoryGroupPrefix('new')).toBe(`${DEFAULT_PROJECT_ID}:`)
  })

  it('extracts valid project ids from paths', () => {
    expect(getProjectIdFromPathname('/projects/summitflow')).toBe('summitflow')
    expect(getProjectIdFromPathname('/projects/summitflow/files')).toBe('summitflow')
    expect(getProjectIdFromPathname('/projects/new')).toBeNull()
    expect(getProjectIdFromPathname('/runtime')).toBeNull()
  })

  it('normalizes empty project ids to the default', () => {
    expect(getRouteProjectId('  ')).toBeNull()
    expect(getProjectIdOrDefault('  ')).toBe(DEFAULT_PROJECT_ID)
    expect(getProjectIdOrDefault(null)).toBe(DEFAULT_PROJECT_ID)
  })
})
