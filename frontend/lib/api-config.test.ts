import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  getApiBaseUrl,
  getTtsBaseUrl,
  getVoiceWsUrl,
  getWsUrl,
} from './api-config'

function mockBrowserLocation(url: string) {
  const parsed = new URL(url)
  vi.stubGlobal('window', {
    location: {
      hostname: parsed.hostname,
      host: parsed.host,
      protocol: parsed.protocol,
      origin: parsed.origin,
    },
  })
}

describe('api-config', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.NEXT_PUBLIC_VOICE_URL
  })

  it('uses direct localhost targets in local development', () => {
    mockBrowserLocation('http://localhost:3001')

    expect(getApiBaseUrl()).toBe('http://localhost:8001')
    expect(getWsUrl('/ws/execution/task-123')).toBe(
      'ws://localhost:8001/ws/execution/task-123',
    )
    expect(getVoiceWsUrl()).toBe(
      'ws://localhost:8003/api/voice/ws?user_id=summitflow_user&app=summitflow&mode=transcribe',
    )
    expect(getTtsBaseUrl()).toBe('http://localhost:8003')
  })

  it('uses same-origin routing on summitflow.dev', () => {
    mockBrowserLocation('https://dev.summitflow.dev')

    expect(getApiBaseUrl()).toBe('')
    expect(getWsUrl('/ws/execution/task-123')).toBe(
      'wss://dev.summitflow.dev/ws/execution/task-123',
    )
    expect(getVoiceWsUrl()).toBe(
      'wss://dev.summitflow.dev/api/voice/ws?user_id=summitflow_user&app=summitflow&mode=transcribe',
    )
    expect(getTtsBaseUrl()).toBe('https://dev.summitflow.dev')
  })

  it('uses same-origin routing on non-production LAN hosts', () => {
    mockBrowserLocation('https://192.168.8.244')

    expect(getApiBaseUrl()).toBe('')
    expect(getWsUrl('/ws/execution/task-123')).toBe(
      'wss://192.168.8.244/ws/execution/task-123',
    )
    expect(getVoiceWsUrl()).toBe(
      'wss://192.168.8.244/api/voice/ws?user_id=summitflow_user&app=summitflow&mode=transcribe',
    )
    expect(getTtsBaseUrl()).toBe('https://192.168.8.244')
  })
})
