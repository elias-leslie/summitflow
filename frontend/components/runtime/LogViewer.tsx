'use client'

import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { runtimeApi } from '@/lib/api/runtime'
import {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'

interface LogViewerProps {
  service: string
  onClose: () => void
}

export function LogViewer({ service, onClose }: LogViewerProps) {
  const [streaming, setStreaming] = useState(false)
  const [streamLines, setStreamLines] = useState<string[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const { data: initialLogs } = useQuery({
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
    if (!streaming) return

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
  }, [streaming, service])

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
          <SheetClose onClose={onClose} />
          <div className="flex gap-2 mt-2">
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
          </div>
        </SheetHeader>

        <SheetBody className="flex-1 overflow-hidden p-0">
          <div
            ref={scrollRef}
            className="h-full overflow-auto px-4 py-3 font-mono text-xs leading-5 text-slate-300"
          >
            {lines.length === 0 ? (
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
