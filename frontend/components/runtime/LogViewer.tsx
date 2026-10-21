'use client'

import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { runtimeApi } from '@/lib/api/runtime'

interface LogViewerProps {
  service: string
  canStream?: boolean
  onClose: () => void
}

export function LogViewer({
  service,
  canStream = true,
  onClose,
}: LogViewerProps) {
  const [streaming, setStreaming] = useState(false)
  const [streamLines, setStreamLines] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const {
    data: initialLogs,
    isPending,
    error,
  } = useQuery({
    queryKey: ['runtime', 'logs', service],
    queryFn: () => runtimeApi.getLogs(service, 200),
    enabled: !streaming,
  })

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [initialLogs, streamLines])

  // SSE streaming
  useEffect(() => {
    if (!streaming || !canStream) return

    const es = new EventSource(runtimeApi.logStreamUrl(service, 50))
    eventSourceRef.current = es

    es.onmessage = (event) => {
      setStreamLines((prev) => [...prev.slice(-1000), event.data])
    }

    es.onerror = () => {
      setStreaming(false)
      es.close()
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [streaming, service, canStream])

  const toggleStream = () => {
    if (streaming) {
      eventSourceRef.current?.close()
      setStreaming(false)
      setStreamLines([])
    } else {
      setStreaming(true)
    }
  }

  const lines = streaming
    ? streamLines
    : (initialLogs?.logs ?? '').split('\n').filter(Boolean)

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="max-w-lg flex flex-col">
        <SheetHeader className="relative">
          <SheetTitle>
            <span className="font-mono text-sm">{service}</span>
          </SheetTitle>
          <SheetDescription>Service logs</SheetDescription>
          <SheetClose />
          <div className="flex gap-2 mt-2">
            {canStream ? (
              <button
                onClick={toggleStream}
                className={clsx(
                  'text-xs px-2.5 py-1 rounded transition-colors',
                  streaming
                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                    : 'bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700',
                )}
              >
                {streaming ? 'Stop streaming' : 'Stream live'}
              </button>
            ) : (
              <p className="text-xs text-slate-400">
                Recent logs only. Live streaming is unavailable for guest
                services.
              </p>
            )}
          </div>
        </SheetHeader>

        <SheetBody className="flex-1 overflow-hidden p-0">
          <div
            ref={scrollRef}
            className="h-full overflow-auto px-4 py-3 font-mono text-xs leading-5 text-slate-300"
          >
            {!streaming && error ? (
              <p className="text-red-400">
                Could not load logs: {error.message}
              </p>
            ) : !streaming && isPending ? (
              <p className="text-slate-500">Loading logs...</p>
            ) : lines.length === 0 ? (
              <p className="text-slate-500">No logs available</p>
            ) : (
              <pre className="whitespace-pre-wrap break-all">
                {lines.join('\n')}
              </pre>
            )}
          </div>
        </SheetBody>
      </SheetContent>
    </Sheet>
  )
}
