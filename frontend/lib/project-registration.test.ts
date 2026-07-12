import { describe, expect, it } from 'vitest'
import {
  buildHealthPreview,
  DEFAULT_HEALTH_ENDPOINT,
  normalizeProjectFormValues,
  normalizeProjectId,
  safeExternalHttpUrl,
  validateProjectForm,
} from './project-registration'

describe('project-registration', () => {
  it('normalizes shared project form values', () => {
    expect(normalizeProjectId('My Project!!')).toBe('my-project')

    expect(
      normalizeProjectFormValues({
        name: '  SummitFlow  ',
        projectId: 'Summit Flow!!',
        baseUrl: 'https://example.com///',
        healthEndpoint: 'healthz',
        rootPath: '/home/testuser/summitflow///',
      }),
    ).toEqual({
      name: 'SummitFlow',
      projectId: 'summit-flow',
      baseUrl: 'https://example.com',
      healthEndpoint: '/healthz',
      rootPath: '/home/testuser/summitflow',
    })
  })

  it('builds a stable health preview and default endpoint', () => {
    expect(buildHealthPreview('https://example.com/', 'healthz')).toBe(
      'https://example.com/healthz',
    )
    expect(buildHealthPreview('', '')).toBe('Disabled')
    expect(
      normalizeProjectFormValues({
        name: 'App',
        projectId: 'app',
        baseUrl: 'https://example.com',
        healthEndpoint: '',
        rootPath: '',
      }).healthEndpoint,
    ).toBe(DEFAULT_HEALTH_ENDPOINT)
  })

  it('validates root path and base url requirements', () => {
    expect(
      validateProjectForm({
        name: '',
        projectId: '',
        baseUrl: 'ftp://example.com',
        healthEndpoint: '',
        rootPath: 'relative/path',
      }),
    ).toEqual({
      name: 'Project name is required',
      projectId: 'Project ID is required',
      baseUrl: 'URL must use http or https',
      rootPath: 'Root path must be an absolute path',
    })
  })

  it('only permits HTTP URLs in external-link sinks', () => {
    expect(safeExternalHttpUrl(' https://example.com/app ')).toBe(
      'https://example.com/app',
    )
    expect(safeExternalHttpUrl('javascript:alert(document.domain)')).toBeNull()
    expect(
      safeExternalHttpUrl('data:text/html,<script>alert(1)</script>'),
    ).toBeNull()
    expect(safeExternalHttpUrl('/relative')).toBeNull()
  })
})
