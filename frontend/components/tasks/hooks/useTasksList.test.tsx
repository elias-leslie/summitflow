import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Task } from '@/lib/api'
import { isStatusFilter, isTypeFilter } from '../TaskFilters'
import { useTasksList } from './useTasksList'

const api = vi.hoisted(() => ({ fetchTasks: vi.fn() }))
vi.mock('@/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api')>()),
  fetchTasks: api.fetchTasks,
}))

const tasks = [
  { id: 'waiting', status: 'pending', blocked_by_incomplete: true },
  { id: 'free', status: 'pending', blocked_by_incomplete: false },
  { id: 'running', status: 'running' },
  { id: 'paused', status: 'paused' },
  { id: 'done', status: 'completed' },
] as Task[]

describe('useTasksList', () => {
  it('filters Blocked to tasks waiting on an unfinished task', async () => {
    api.fetchTasks.mockResolvedValue({ tasks, total: tasks.length })
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )

    const { result } = renderHook(
      () =>
        useTasksList(
          'summitflow',
          { type: 'all', status: 'blocked', priority: 'all' },
          (list) => list,
        ),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(api.fetchTasks).toHaveBeenCalledWith('summitflow', {
      limit: 500,
      include: 'blockers',
    })
    expect(result.current.filteredTasks.map((t) => t.id)).toEqual(['waiting'])
  })

  it('filters Open the way the dashboard counts: not paused and not finished', async () => {
    api.fetchTasks.mockResolvedValue({ tasks, total: tasks.length })
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(
      () =>
        useTasksList(
          'summitflow',
          { type: 'all', status: 'active', priority: 'all' },
          (list) => list,
        ),
      { wrapper },
    )
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.filteredTasks.map((t) => t.id)).toEqual([
      'waiting',
      'free',
      'running',
    ])
  })

  it('accepts every status filter a link can carry, including paused', () => {
    for (const value of ['active', 'blocked', 'paused', 'cancelled', 'all'])
      expect(isStatusFilter(value)).toBe(true)
    expect(isStatusFilter('conflicted')).toBe(false)
    expect(isStatusFilter(null)).toBe(false)
  })

  it('filters a type group to every type the dashboard tile counts', async () => {
    const typed = [
      { id: 't', status: 'pending', task_type: 'task' },
      { id: 'r', status: 'pending', task_type: 'refactor' },
      { id: 'b', status: 'pending', task_type: 'bug' },
      { id: 'g', status: 'pending', task_type: 'regression' },
      { id: 'f', status: 'pending', task_type: 'feature' },
    ] as Task[]
    api.fetchTasks.mockResolvedValue({ tasks: typed, total: typed.length })
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const ids = async (type: string) => {
      const { result } = renderHook(
        () =>
          useTasksList(
            'summitflow',
            {
              type: type as 'all',
              status: 'active',
              priority: 'all',
            },
            (list) => list,
          ),
        { wrapper },
      )
      await waitFor(() => expect(result.current.isLoading).toBe(false))
      return result.current.filteredTasks.map((t) => t.id)
    }
    expect(await ids('task,refactor')).toEqual(['t', 'r'])
    expect(await ids('bug,regression')).toEqual(['b', 'g'])
    expect(await ids('bug')).toEqual(['b'])
  })

  it('accepts every type filter a link can carry, including the tile groups', () => {
    for (const value of ['all', 'refactor', 'task,refactor', 'bug,regression'])
      expect(isTypeFilter(value)).toBe(true)
    expect(isTypeFilter('task,bug')).toBe(false)
    expect(isTypeFilter(null)).toBe(false)
  })
})
