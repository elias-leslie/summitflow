'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { type LiveSessionControl, runtimeApi } from '@/lib/api/runtime'
import {
  LiveSessionLoading,
  LiveSessionUnavailable,
} from './LiveSessionFallback'
import { LiveSessionHeader } from './LiveSessionHeader'
import { LiveSessionSidebar } from './LiveSessionSidebar'
import { LiveSessionViewport } from './LiveSessionViewport'
import { useLiveSessionInput } from './live-session-input-hooks'
import {
  useLiveSessionFrameDisplay,
  useLiveSessionOperatorToken,
  useLiveSessionSecureText,
} from './live-session-workspace-hooks'
import {
  FRAME_REFETCH_INTERVAL_MS,
  LIVE_SESSIONS_QUERY_KEY,
  liveSessionFrameQueryKey,
  liveSessionQueryKey,
  SESSION_REFETCH_INTERVAL_MS,
} from './live-session-workspace-model'

export {
  mapLiveFramePoint,
  normalizeAnnotationBox,
} from './live-session-workspace-model'

interface LiveSessionWorkspaceProps {
  sessionId: string
}

export function LiveSessionWorkspace({ sessionId }: LiveSessionWorkspaceProps) {
  const queryClient = useQueryClient()
  const [targetUrl, setTargetUrl] = useState('')
  const { operatorToken, tokenReady } = useLiveSessionOperatorToken(sessionId)

  const sessionQuery = useQuery({
    queryKey: liveSessionQueryKey(sessionId),
    queryFn: () => runtimeApi.getLiveSession(sessionId),
    refetchInterval: SESSION_REFETCH_INTERVAL_MS,
  })
  const frameQuery = useQuery({
    queryKey: liveSessionFrameQueryKey(sessionId, !!operatorToken),
    queryFn: () => runtimeApi.getLiveSessionFrame(sessionId, operatorToken),
    enabled:
      tokenReady &&
      sessionQuery.data?.state === 'active' &&
      (!sessionQuery.data.token_required || !!operatorToken),
    refetchInterval: FRAME_REFETCH_INTERVAL_MS,
    staleTime: 0,
    gcTime: 0,
    retry: false,
  })
  const controlMutation = useMutation({
    mutationFn: (control: LiveSessionControl) =>
      runtimeApi.controlLiveSession(sessionId, control, operatorToken),
    onSuccess: invalidateSession,
  })
  const sensitiveMutation = useMutation({
    mutationFn: (sensitive: boolean) =>
      runtimeApi.setLiveSessionSensitive(sessionId, sensitive, operatorToken),
    onSuccess: invalidateSession,
  })
  const teardownMutation = useMutation({
    mutationFn: () => runtimeApi.teardownLiveSession(sessionId),
    onSuccess: () => {
      invalidateSession()
      queryClient.invalidateQueries({ queryKey: LIVE_SESSIONS_QUERY_KEY })
    },
  })
  const controlGrantMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      runtimeApi.setLiveSessionControlGrant(sessionId, enabled, operatorToken),
    onSuccess: invalidateSession,
  })

  const session = sessionQuery.data
  const frame = frameQuery.data
  const tokenMissing = !!session?.token_required && !operatorToken
  const canSendInput = !!operatorToken && !!session?.control_enabled
  const { viewportRef, frameImageRef, frameDisplay, updateFrameDisplay } =
    useLiveSessionFrameDisplay(frame?.image_data_url)
  const liveInput = useLiveSessionInput({
    frame,
    frameImageRef,
    viewportRef,
    sessionActive: session?.state === 'active',
    canSendInput,
    onSendControl: (control) => controlMutation.mutate(control),
  })
  const {
    secureTextRef,
    secureTextSending,
    secureTextError,
    secureTextStatus,
    submitSecureText,
    pasteClipboardSecureText,
    clearSecureText,
  } = useLiveSessionSecureText({
    sessionId,
    operatorToken,
    sessionActive: session?.state === 'active',
    canSendInput,
    onSent: invalidateSession,
    focusViewport: () => viewportRef.current?.focus(),
  })

  function invalidateSession(): void {
    queryClient.invalidateQueries({ queryKey: liveSessionQueryKey(sessionId) })
  }

  function navigate(): void {
    const nextUrl = targetUrl.trim()
    if (!canSendInput) return
    if (!nextUrl) return
    liveInput.sendControl({
      action: 'navigate',
      target_url: nextUrl,
    })
  }

  if (sessionQuery.isLoading) {
    return <LiveSessionLoading />
  }

  if (sessionQuery.error || !session) {
    return <LiveSessionUnavailable error={sessionQuery.error} />
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <LiveSessionHeader
        session={session}
        tokenMissing={tokenMissing}
        hasOperatorToken={!!operatorToken}
        sensitivePending={sensitiveMutation.isPending}
        controlGrantPending={controlGrantMutation.isPending}
        teardownPending={teardownMutation.isPending}
        onRefreshFrame={() => frameQuery.refetch()}
        onToggleSensitive={() => sensitiveMutation.mutate(!session.sensitive)}
        onToggleControlGrant={() =>
          controlGrantMutation.mutate(!session.control_enabled)
        }
        onTeardown={() => teardownMutation.mutate()}
      />

      <div className="grid gap-3 px-4 py-3 lg:grid-cols-[1fr_320px]">
        <section className="min-w-0">
          <LiveSessionViewport
            viewportRef={viewportRef}
            frameImageRef={frameImageRef}
            frameImageUrl={frame?.image_data_url}
            tokenMissing={tokenMissing}
            annotations={liveInput.annotations}
            frameDisplay={frameDisplay}
            viewportWidth={session.viewport_width}
            viewportHeight={session.viewport_height}
            onFrameImageLoad={updateFrameDisplay}
            onClick={liveInput.handleClick}
            onMouseDown={liveInput.handleMouseDown}
            onMouseUp={liveInput.handleMouseUp}
            onKeyDown={liveInput.handleKey}
            onWheel={liveInput.handleWheel}
          />
        </section>

        <LiveSessionSidebar
          session={session}
          interactionMode={liveInput.interactionMode}
          annotationsCount={liveInput.annotations.length}
          tokenMissing={tokenMissing}
          frameFetching={frameQuery.isFetching}
          targetUrl={targetUrl}
          canSendInput={canSendInput}
          secureTextRef={secureTextRef}
          secureTextSending={secureTextSending}
          secureTextStatus={secureTextStatus}
          secureTextError={secureTextError}
          controlError={controlMutation.error}
          frameError={frameQuery.error}
          onInteractionModeChange={liveInput.setInteractionMode}
          onClearAnnotations={liveInput.clearAnnotations}
          onTargetUrlChange={setTargetUrl}
          onNavigate={navigate}
          onSubmitSecureText={submitSecureText}
          onPasteClipboardSecureText={pasteClipboardSecureText}
          onClearSecureText={clearSecureText}
          onResizeViewport={(width, height) =>
            liveInput.sendControl({
              action: 'resize',
              viewport_width: width,
              viewport_height: height,
            })
          }
        />
      </div>
    </div>
  )
}
