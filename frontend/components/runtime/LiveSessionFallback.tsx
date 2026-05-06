'use client'

import { Loader2 } from 'lucide-react'

interface LiveSessionUnavailableProps {
  error: unknown
}

export function LiveSessionLoading() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-400">
      <Loader2 className="h-6 w-6 animate-spin" />
    </div>
  )
}

export function LiveSessionUnavailable({ error }: LiveSessionUnavailableProps) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 px-6 text-sm text-rose-300">
      {error instanceof Error ? error.message : 'Live session unavailable'}
    </div>
  )
}
