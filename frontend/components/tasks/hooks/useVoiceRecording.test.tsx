import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVoiceRecording } from './useVoiceRecording'

const apiConfigMocks = vi.hoisted(() => ({
  getVoiceWsUrl: vi.fn(),
}))

vi.mock('@/lib/api-config', () => ({
  getVoiceWsUrl: apiConfigMocks.getVoiceWsUrl,
}))

describe('useVoiceRecording', () => {
  let originalMediaDevices: MediaDevices

  beforeEach(() => {
    vi.clearAllMocks()
    originalMediaDevices = navigator.mediaDevices
  })

  afterEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: originalMediaDevices,
    })
  })

  it('stops the microphone stream when voice transport is unavailable', async () => {
    const stop = vi.fn()
    const getUserMedia = vi.fn().mockResolvedValue({
      getTracks: () => [{ stop }],
    })

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia },
    })
    apiConfigMocks.getVoiceWsUrl.mockReturnValue(null)

    const { result } = renderHook(() =>
      useVoiceRecording({
        onTranscription: vi.fn(),
      }),
    )

    result.current.toggleRecording()

    await waitFor(() => {
      expect(result.current.error).toBe('Voice service not configured')
    })

    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(stop).toHaveBeenCalledTimes(1)
    expect(result.current.isRecording).toBe(false)
  })
})
