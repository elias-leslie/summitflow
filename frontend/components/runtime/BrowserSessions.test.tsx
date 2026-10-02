import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
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
  browserStreamUrl,
  parseBrowserSession,
  parseBrowserStreamEvent,
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
}
const second: BrowserSession = {
  ...first,
  name: 'agent-two',
  actor: 'agent:second',
  paused: true,
}

class Socket {
  static OPEN = 1
  static CONNECTING = 0
  static instances: Socket[] = []
  readyState = 1
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = 3
    this.onclose?.()
  })
  constructor(public url: string) {
    Socket.instances.push(this)
  }
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
  Socket.instances = []
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
    vi.stubGlobal('WebSocket', Socket)
    mount()
    const choice = await screen.findByRole('button', {
      name: /agent-one Owner/,
    })
    expect(screen.queryByRole('button', { name: 'Pause for human' })).toBeNull()
    expect(Socket.instances).toHaveLength(0)
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
    expect(Socket.instances).toHaveLength(0)
  })

  it('disconnects the retained target when changing selection and never reconnects automatically', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([first, second])
    vi.stubGlobal('WebSocket', Socket)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open live view' }))
    await waitFor(() => expect(Socket.instances).toHaveLength(1))
    const socket = Socket.instances[0]
    expect(new URL(socket.url).host).toBe(window.location.host)
    expect(new URL(socket.url).pathname).toBe('/ws/browser-sessions/agent-two')
    expect(new URL(socket.url).searchParams.get('actor')).toBe(second.actor)
    fireEvent.click(screen.getByRole('button', { name: /agent-one Owner/ }))
    expect(socket.close).toHaveBeenCalled()
    expect(Socket.instances).toHaveLength(1)
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

  it('makes empty and failed inventories visible', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([])
    const result = mount()
    await screen.findByText(/No managed browser sessions/)
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
  it('waits for owner release acknowledgement before lifecycle HTTP', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([second])
    vi.mocked(browserSessionsApi.change).mockResolvedValue({
      ...second,
      paused: false,
    })
    vi.stubGlobal('WebSocket', Socket)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open live view' }))
    const socket = Socket.instances[0]
    fireEvent.click(screen.getByRole('button', { name: 'Resume automation' }))
    expect(socket.send).toHaveBeenLastCalledWith('{"type":"release"}')
    expect(browserSessionsApi.change).not.toHaveBeenCalled()
    expect(
      screen.getByRole('button', { name: /agent-two Owner/ }),
    ).toBeDisabled()
    act(() =>
      socket.onmessage?.(
        new MessageEvent('message', { data: '{"type":"released"}' }),
      ),
    )
    await waitFor(() =>
      expect(browserSessionsApi.change).toHaveBeenCalledWith(second, 'resume'),
    )
    expect(socket.close).toHaveBeenCalled()
  })

  it('does not send lifecycle HTTP when release is unconfirmed', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([second])
    vi.stubGlobal('WebSocket', Socket)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open live view' }))
    fireEvent.click(screen.getByRole('button', { name: 'Close session' }))
    act(() => Socket.instances[0].close())
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'release was not confirmed',
    )
    expect(browserSessionsApi.change).not.toHaveBeenCalled()
  })
  it('shows closed selections and denies further controls', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([
      { ...second, state: 'closed', paused: false },
    ])
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    expect(screen.getByText(/This session is closed/)).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Open live view' })).toBeNull()
  })

  it('forwards native keys only after a frame and clears disconnected content', async () => {
    vi.mocked(browserSessionsApi.list).mockResolvedValue([second])
    vi.stubGlobal('WebSocket', Socket)
    class FrameImage {
      onload: (() => void) | null = null
      onerror: (() => void) | null = null
      set src(_value: string) {
        this.onload?.()
      }
    }
    vi.stubGlobal('Image', FrameImage)
    const clearRect = vi.fn()
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      drawImage: vi.fn(),
      clearRect,
    } as unknown as CanvasRenderingContext2D)
    mount()
    fireEvent.click(
      await screen.findByRole('button', { name: /agent-two Owner/ }),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Open live view' }))
    const canvas = screen.getByLabelText('Live page for agent-two')
    const socket = Socket.instances[0]
    fireEvent.keyDown(canvas, { key: 'r', code: 'KeyR' })
    expect(socket.send).not.toHaveBeenCalled()
    act(() =>
      socket.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'frame',
            seq: 5,
            data: 'AA==',
            metadata: { deviceWidth: 100, deviceHeight: 50 },
          }),
        }),
      ),
    )
    fireEvent.keyDown(canvas, { key: 'r', code: 'KeyR' })
    expect(socket.send).toHaveBeenLastCalledWith(
      JSON.stringify({
        type: 'input_keyboard',
        eventType: 'keyDown',
        key: 'r',
        code: 'KeyR',
        windowsVirtualKeyCode: 82,
        modifiers: 0,
        text: 'r',
      }),
    )
    act(() => socket.close())
    expect(clearRect).toHaveBeenCalled()
    expect(screen.getByText(/Live view ended/)).toBeVisible()
    fireEvent.keyDown(canvas, { key: 'x', code: 'KeyX' })
    expect(socket.send).toHaveBeenCalledTimes(2)
  })
})

describe('browser IO validation', () => {
  it('rejects malformed session and native frame payloads', () => {
    expect(() => parseBrowserSession({ ...first, paused: 'true' })).toThrow()
    expect(() =>
      parseBrowserStreamEvent(
        JSON.stringify({
          type: 'frame',
          data: '<svg/>',
          seq: 1,
          metadata: { deviceWidth: 10, deviceHeight: 10 },
        }),
      ),
    ).toThrow()
    expect(() =>
      parseBrowserStreamEvent(
        JSON.stringify({
          type: 'bound',
          binding: { target_id: null },
          page: {},
        }),
      ),
    ).toThrow()
    expect(() =>
      parseBrowserStreamEvent('{"type":"command","command":"eval"}'),
    ).toThrow()
  })

  it('accepts current core frame metadata and keeps websocket URLs same-origin', () => {
    expect(
      parseBrowserStreamEvent(
        JSON.stringify({
          type: 'frame',
          data: 'AA==',
          seq: 4,
          metadata: { deviceWidth: 100, deviceHeight: 50 },
        }),
      ),
    ).toEqual({ type: 'frame', data: 'AA==', seq: 4, width: 100, height: 50 })
    const url = new URL(browserStreamUrl(second))
    expect(url.host).toBe(window.location.host)
    expect(url.searchParams.get('actor')).toBe(second.actor)
  })

  it('displays locations without URL credentials or authorization queries', () => {
    expect(
      parseBrowserStreamEvent(
        '{"type":"url","url":"https://user:private@fixture.test/callback?code=private&token=private#private"}',
      ),
    ).toEqual({ type: 'url', url: 'https://fixture.test/callback' })
  })
})
