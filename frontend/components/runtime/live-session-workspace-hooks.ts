'use client'

import { type FormEvent, useEffect, useRef, useState } from 'react'
import { runtimeApi } from '@/lib/api/runtime'
import {
  EMPTY_FRAME_DISPLAY,
  type FrameDisplayRect,
  liveSessionTokenStorageKey,
} from './live-session-workspace-model'

interface SecureTextParams {
  sessionId: string
  operatorToken: string | null
  sessionActive: boolean
  canSendInput: boolean
  onSent: () => void
  focusViewport: () => void
}

export function useLiveSessionOperatorToken(sessionId: string) {
  const [operatorToken, setOperatorToken] = useState<string | null>(null)
  const [tokenReady, setTokenReady] = useState(false)

  useEffect(() => {
    const storageKey = liveSessionTokenStorageKey(sessionId)
    const hash = window.location.hash.replace(/^#/, '')
    const params = new URLSearchParams(hash)
    const fragmentToken = params.get('token')
    const storedToken = window.sessionStorage.getItem(storageKey)
    const token = fragmentToken || storedToken
    if (token) {
      window.sessionStorage.setItem(storageKey, token)
      setOperatorToken(token)
    }
    if (fragmentToken) {
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}`,
      )
    }
    setTokenReady(true)
  }, [sessionId])

  return { operatorToken, tokenReady }
}

export function useLiveSessionFrameDisplay(
  frameImageUrl: string | null | undefined,
) {
  const viewportRef = useRef<HTMLButtonElement>(null)
  const frameImageRef = useRef<HTMLImageElement>(null)
  const [frameDisplay, setFrameDisplay] =
    useState<FrameDisplayRect>(EMPTY_FRAME_DISPLAY)

  function updateFrameDisplay(): void {
    const viewportRect = viewportRef.current?.getBoundingClientRect()
    const imageRect = frameImageRef.current?.getBoundingClientRect()
    if (!viewportRect || !imageRect || viewportRect.width <= 0) {
      setFrameDisplay(EMPTY_FRAME_DISPLAY)
      return
    }
    setFrameDisplay({
      leftPercent:
        ((imageRect.left - viewportRect.left) / viewportRect.width) * 100,
      topPercent:
        ((imageRect.top - viewportRect.top) / viewportRect.height) * 100,
      widthPercent: (imageRect.width / viewportRect.width) * 100,
      heightPercent: (imageRect.height / viewportRect.height) * 100,
    })
  }

  useEffect(() => {
    updateFrameDisplay()
    window.addEventListener('resize', updateFrameDisplay)
    return () => window.removeEventListener('resize', updateFrameDisplay)
  }, [frameImageUrl])

  return { viewportRef, frameImageRef, frameDisplay, updateFrameDisplay }
}

export function useLiveSessionSecureText({
  sessionId,
  operatorToken,
  sessionActive,
  canSendInput,
  onSent,
  focusViewport,
}: SecureTextParams) {
  const secureTextRef = useRef<HTMLInputElement>(null)
  const [secureTextSending, setSecureTextSending] = useState(false)
  const [secureTextError, setSecureTextError] = useState<string | null>(null)
  const [secureTextStatus, setSecureTextStatus] = useState<string | null>(null)

  async function transmitSecureText(text: string): Promise<void> {
    if (!sessionActive) return
    if (!canSendInput) return
    if (!text) return
    setSecureTextSending(true)
    setSecureTextError(null)
    setSecureTextStatus(null)
    try {
      await runtimeApi.secureTextLiveSession(sessionId, text, operatorToken)
      if (secureTextRef.current) {
        secureTextRef.current.value = ''
        secureTextRef.current.blur()
      }
      setSecureTextStatus('Sent')
      onSent()
      focusViewport()
    } catch (error) {
      setSecureTextError(
        error instanceof Error ? error.message : 'Failed to send secure text',
      )
    } finally {
      setSecureTextSending(false)
    }
  }

  function submitSecureText(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault()
    void transmitSecureText(secureTextRef.current?.value ?? '')
  }

  async function pasteClipboardSecureText(): Promise<void> {
    setSecureTextError(null)
    setSecureTextStatus(null)
    if (!navigator.clipboard?.readText) {
      setSecureTextError('Clipboard unavailable')
      return
    }
    try {
      const clipboardText = await navigator.clipboard.readText()
      await transmitSecureText(clipboardText)
    } catch (error) {
      setSecureTextError(
        error instanceof Error ? error.message : 'Failed to read clipboard',
      )
    }
  }

  function clearSecureText(): void {
    if (secureTextRef.current) {
      secureTextRef.current.value = ''
      secureTextRef.current.focus()
    }
    setSecureTextError(null)
    setSecureTextStatus(null)
  }

  return {
    secureTextRef,
    secureTextSending,
    secureTextError,
    secureTextStatus,
    submitSecureText,
    pasteClipboardSecureText,
    clearSecureText,
  }
}
