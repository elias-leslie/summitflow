import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fileQueryKeys } from '@/lib/hooks/useFileExplorer'
import { FileContextMenu } from './FileContextMenu'

const api = vi.hoisted(() => ({ deletePath: vi.fn(), renamePath: vi.fn() }))
vi.mock('@/lib/api/files', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/files')>()),
  deletePath: api.deletePath,
  renamePath: api.renamePath,
}))

const scope = { kind: 'workspace' } as const
const target = {
  path: 'exchange/ut-test.txt',
  absolutePath: '/srv/workspaces/exchange/ut-test.txt',
  name: 'ut-test.txt',
  isDirectory: false,
  scope,
}

function renderMenu(client: QueryClient) {
  const onMutated = vi.fn()
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={client}>
      <FileContextMenu
        position={{ x: 0, y: 0 }}
        target={target}
        onClose={onClose}
        onMutated={onMutated}
      />
    </QueryClientProvider>,
  )
  return { onMutated, onClose }
}

function seededClient() {
  const client = new QueryClient()
  client.setQueryData(fileQueryKeys.content(scope, target.path), {
    content: 'old',
  })
  client.setQueryData(fileQueryKeys.content(scope, 'exchange/other.txt'), {
    content: 'kept',
  })
  return client
}

describe('FileContextMenu after a path is removed', () => {
  afterEach(() => vi.restoreAllMocks())

  it('delete drops the removed file from the cache and refreshes only the tree', async () => {
    api.deletePath.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const client = seededClient()
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    const { onMutated, onClose } = renderMenu(client)

    fireEvent.click(screen.getByText('Delete'))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(api.deletePath).toHaveBeenCalledWith(scope, 'exchange/ut-test.txt')
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: fileQueryKeys.trees(scope),
    })
    expect(onMutated).toHaveBeenCalled()
    expect(
      client.getQueryData(fileQueryKeys.content(scope, target.path)),
    ).toBeUndefined()
    expect(
      client.getQueryData(fileQueryKeys.content(scope, 'exchange/other.txt')),
    ).toEqual({ content: 'kept' })
  })

  it('rename drops the old path from the cache too', async () => {
    api.renamePath.mockResolvedValue(undefined)
    vi.spyOn(window, 'prompt').mockReturnValue('ut-test-renamed.txt')
    const client = seededClient()
    const { onMutated, onClose } = renderMenu(client)

    fireEvent.click(screen.getByText('Rename'))

    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(api.renamePath).toHaveBeenCalledWith(
      scope,
      'exchange/ut-test.txt',
      'ut-test-renamed.txt',
    )
    expect(onMutated).toHaveBeenCalled()
    expect(
      client.getQueryData(fileQueryKeys.content(scope, target.path)),
    ).toBeUndefined()
  })
})
