import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  type BrowserSession,
  browserSessionsApi,
  parseBrowserSession,
} from '@/lib/api/browser-sessions'
import { BrowserSessions } from './BrowserSessions'

vi.mock('@/lib/api/browser-sessions', async (original) => ({
  ...(await original<typeof import('@/lib/api/browser-sessions')>()),
  browserSessionsApi: { list: vi.fn(), change: vi.fn() },
}))

const first: BrowserSession = {
  name: 'agent-one',
  actor: 'agent:first',
  state: 'active',
  paused: false,
  runtime_state: 'running',
  last_used_ms: null,
  location: 'proxmox',
  pause_reason: null,
}
const second: BrowserSession = {
  ...first,
  name: 'agent-two',
  actor: 'agent:second',
  paused: true,
  location: 'local',
}

function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <BrowserSessions />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.resetAllMocks()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('Runtime managed browser sessions', () => {
  it('requires explicit selection and binds controls to its retained owner', async () => {
    let sessions = [first, second]
    vi.mocked(browserSessionsApi.list).mockImplementation(async () => sessions)
    vi.mocked(browserSessionsApi.change).mockImplementation(
      async (selected, action) => {
        expect(action).toBe('pause')
        const changed = { ...first, paused: true }
        sessions = [changed, second]
        expect(selected).toMatchObject({ name: first.name, actor: first.actor })
        return changed
      },
    )
    mount()
    const choice = await screen.findByRole('button', {
      name: /agent-one Owner/,
    })
    expect(screen.queryByRole('button', { name: 'Pause for human' })).toBeNull()
    fireEvent.click(choice)
    expect(
      screen.getByRole('button', { name: 'Open live view' }),
    ).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Pause for human' }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Open live view' }),
      ).toBeEnabled(),
    )
  })

  it('opens the paused session in its own assist window', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([first, second])
    const open = vi.fn()
    vi.stubGlobal('open', open)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open live view' }))
    expect(open).toHaveBeenCalledWith(
      '/browser-assist/agent-two',
      'browser-assist-agent-two',
      'popup,width=1280,height=900',
    )
    expect(browserSessionsApi.change).not.toHaveBeenCalled()
  })

  it('resumes and closes through the selected owner', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([second])
    vi.mocked(browserSessionsApi.change).mockResolvedValue({
      ...second,
      paused: false,
    })
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Resume automation' }))
    await waitFor(() =>
      expect(browserSessionsApi.change).toHaveBeenCalledWith(second, 'resume'),
    )
  })

  it('stops displaying a stale selection after its owner changes', async () => {
    let sessions = [second]
    vi.mocked(browserSessionsApi.list).mockImplementation(async () => sessions)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    sessions = [{ ...second, actor: 'agent:replacement' }]
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
    await screen.findByText(
      /This selection is unavailable or its owner changed/,
    )
    expect(
      screen.queryByRole('button', { name: 'Resume automation' }),
    ).toBeNull()
    expect(browserSessionsApi.change).not.toHaveBeenCalled()
  })

  it('labels where each session browser runs', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([
      first,
      second,
      { ...first, name: 'agent-idle', runtime_state: null, location: null },
    ])
    mount()
    expect(
      await screen.findByRole('button', { name: /agent-one .*Proxmox VM/ }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /agent-two .*this workstation/ }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /agent-idle/ }))
    expect(
      screen.getByText(/Automation can use this session/).textContent,
    ).not.toMatch(/Browser/)
    fireEvent.click(screen.getByRole('button', { name: /agent-one/ }))
    expect(
      screen.getByText(/Browser on the Proxmox VM\. Automation/),
    ).toBeInTheDocument()
  })

  it('makes empty and failed inventories visible', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([])
    const result = mount()
    await screen.findByText(/No open browser sessions/)
    result.unmount()
    vi.mocked(browserSessionsApi.list).mockRejectedValue(
      new Error('Owner unavailable'),
    )
    mount()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Owner unavailable',
    )
  })
})

describe('native browser controls', () => {
  it('shows closed selections and denies further controls', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([
      { ...second, state: 'closed', paused: false },
    ])
    mount()
    // Closed sessions are listed only on request.
    fireEvent.click(
      await screen.findByRole('button', { name: 'Show closed sessions (1)' }),
    )
    fireEvent.click(screen.getByRole('button', { name: /agent-two Owner/ }))
    expect(screen.getByText(/This session is closed/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Open live view' })).toBeNull()
  })
})

describe('owner hand-off', () => {
  it('selects the linked paused session and shows its reason', async () => {
    window.history.replaceState(
      null,
      '',
      '/runtime?browser=agent-two&actor=agent%3Asecond',
    )
    vi.mocked(browserSessionsApi.list).mockResolvedValue([
      first,
      { ...second, pause_reason: 'login needed: example.com' },
    ])
    mount()
    expect(
      await screen.findByText(
        'Agent is waiting for you: login needed: example.com',
      ),
    ).toBeVisible()
    expect(screen.getByRole('button', { name: 'Open live view' })).toBeEnabled()
    window.history.replaceState(null, '', '/')
  })
})

describe('browser IO validation', () => {
  it('rejects malformed session payloads', () => {
    expect(() => parseBrowserSession({ ...first, paused: 'true' })).toThrow()
    expect(() =>
      parseBrowserSession({ ...first, location: '10.0.0.5' }),
    ).toThrow()
    const { location: _omitted, ...legacy } = first
    expect(parseBrowserSession(legacy).location).toBeNull()
  })
})
