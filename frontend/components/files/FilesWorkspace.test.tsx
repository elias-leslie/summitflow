import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FilesClient } from '@/app/(app)/projects/[id]/files/FilesClient'
import { resolveReadmeUrl } from '../projects/ProjectReadmeMarkdown'

const navigation = vi.hoisted(() => ({ query: '' }))
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'summitflow' }),
  useSearchParams: () => new URLSearchParams(navigation.query),
}))
vi.mock('@uiw/react-codemirror', () => ({
  default: ({ value }: { value: string }) => <pre>{value}</pre>,
}))

function renderLinkedWorkspace(url: string) {
  navigation.query = new URL(url, 'https://summitflow.test').search
  const requests: URL[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = new URL(String(input), 'https://summitflow.test')
    requests.push(url)
    const path = url.searchParams.get('path') || ''
    const body = url.pathname.endsWith('/tree')
      ? {
          entries: path
            ? [
                {
                  name: 'config.json',
                  path: `${path}/config.json`,
                  absolute_path: `/repo/${path}/config.json`,
                  is_directory: false,
                  extension: '.json',
                },
              ]
            : [],
          path,
          absolute_path: `/repo/${path}`,
          total: path ? 1 : 0,
        }
      : {
          path,
          name: 'config.json',
          content: 'Selected file content',
          size: 21,
          lines: 1,
          extension: '.json',
          is_binary: false,
          language: null,
          truncated: false,
        }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <FilesClient />
    </QueryClientProvider>,
  )
  return requests
}

describe('README file browser links', () => {
  afterEach(() => vi.restoreAllMocks())

  it.each([
    'profiles/',
    'backend/app/api/research/',
    'scripts/systemd/',
    'tests/',
  ])('browses %s without requesting its file content', async (path) => {
    const href = resolveReadmeUrl(path, 'summitflow', false)
    expect(href).toBeDefined()
    const requests = renderLinkedWorkspace(href || '')
    expect(
      await screen.findByRole('button', { name: 'config.json' }),
    ).toBeInTheDocument()
    expect(
      requests.some(
        (url) =>
          url.pathname.endsWith('/tree') &&
          url.searchParams.get('path') === path.slice(0, -1),
      ),
    ).toBe(true)
    expect(requests.some((url) => url.pathname.endsWith('/content'))).toBe(
      false,
    )
    expect(screen.getByRole('heading', { level: 2 })).toHaveTextContent(
      path.split('/').at(-2) || '',
    )

    fireEvent.click(screen.getByRole('button', { name: 'config.json' }))
    expect(await screen.findByText('Selected file content')).toBeInTheDocument()
    expect(
      requests.some(
        (url) =>
          url.pathname.endsWith('/content') &&
          url.searchParams.get('path') === `${path}config.json`,
      ),
    ).toBe(true)
  })

  it('continues to open direct file links in the viewer', async () => {
    const requests = renderLinkedWorkspace(
      '/projects/summitflow/files?path=profiles%2Fconfig.json',
    )
    expect(await screen.findByText('Selected file content')).toBeInTheDocument()
    expect(
      requests.some(
        (url) =>
          url.pathname.endsWith('/content') &&
          url.searchParams.get('path') === 'profiles/config.json',
      ),
    ).toBe(true)
  })
})
