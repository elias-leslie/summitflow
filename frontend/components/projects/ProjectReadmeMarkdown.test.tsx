import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  ProjectReadmeMarkdown,
  resolveReadmeUrl,
} from './ProjectReadmeMarkdown'

describe('README Markdown', () => {
  it('gives local anchors matching unique heading IDs', () => {
    render(
      <ProjectReadmeMarkdown
        projectId="summitflow"
        content={
          '[Setup](#getting-started)\n\n## Getting **started**\n\n## Getting started'
        }
      />,
    )
    expect(screen.getByRole('link', { name: 'Setup' })).toHaveAttribute(
      'href',
      '#getting-started',
    )
    const headings = screen.getAllByRole('heading', { name: 'Getting started' })
    expect(headings[0]).toHaveAttribute('id', 'getting-started')
    expect(headings[1]).toHaveAttribute('id', 'getting-started-1')
  })

  it.each([
    'javascript:alert(1)',
    'data:image/svg+xml,test',
    'file:///etc/passwd',
    '//external.test/pixel',
    '../outside.md',
    '%2e%2e/outside.md',
    'docs/%5cfile.md',
  ])('disallows unsafe or escaping URL %s', (url) => {
    expect(resolveReadmeUrl(url, 'summitflow', false)).toBeUndefined()
    expect(resolveReadmeUrl(url, 'summitflow', true)).toBeUndefined()
  })

  it('retains safe external documentation links and normalizes repository paths', () => {
    expect(
      resolveReadmeUrl('https://docs.example.test/guide', 'summitflow', false),
    ).toBe('https://docs.example.test/guide')
    expect(resolveReadmeUrl('./docs/../guide.md', 'summitflow', false)).toBe(
      '/projects/summitflow/files?path=guide.md',
    )
    expect(
      resolveReadmeUrl('mailto:team@example.test', 'summitflow', true),
    ).toBeUndefined()
  })

  it.each([
    'profiles/',
    'backend/app/api/research/',
    'scripts/systemd/',
    'tests/',
  ])('keeps directory intent for %s', (path) => {
    render(
      <ProjectReadmeMarkdown
        projectId="summitflow"
        content={`[Directory](${path})`}
      />,
    )
    expect(screen.getByRole('link', { name: 'Directory' })).toHaveAttribute(
      'href',
      `/projects/summitflow/files?directory=${encodeURIComponent(path.slice(0, -1))}`,
    )
  })

  it('normalizes a link to the repository root as a directory', () => {
    expect(resolveReadmeUrl('./', 'summitflow', false)).toBe(
      '/projects/summitflow/files?directory=',
    )
    expect(resolveReadmeUrl('profiles%2F', 'summitflow', false)).toBe(
      '/projects/summitflow/files?directory=profiles',
    )
  })
})
