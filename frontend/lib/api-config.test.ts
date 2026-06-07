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

  it('uses same-origin routing on production host', () => {
    mockBrowserLocation('https://summitflow.example.com')

    expect(getApiBaseUrl()).toBe('')
    expect(getWsUrl('/ws/execution/task-123')).toBe(
      'wss://summitflow.example.com/ws/execution/task-123',
    )
    expect(getVoiceWsUrl()).toBe(
      'wss://summitflow.example.com/api/voice/ws?user_id=summitflow_user&app=summitflow&mode=transcribe',
    )
    expect(getTtsBaseUrl()).toBe('https://summitflow.example.com')
  })

  it('uses same-origin routing on non-production LAN hosts', () => {
    mockBrowserLocation('https://192.0.2.44')

    expect(getApiBaseUrl()).toBe('')
    expect(getWsUrl('/ws/execution/task-123')).toBe(
      'wss://192.0.2.44/ws/execution/task-123',
    )
    expect(getVoiceWsUrl()).toBe(
      'wss://192.0.2.44/api/voice/ws?user_id=summitflow_user&app=summitflow&mode=transcribe',
    )
    expect(getTtsBaseUrl()).toBe('https://192.0.2.44')
  })
})
