'use client'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { fetchAuthMe } from '@/lib/api/auth'

export function AppAuthGate({ children }: { children: React.ReactNode }) {
  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: ['auth-me'],
    queryFn: fetchAuthMe,
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading SummitFlow...
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 p-6 text-center">
        <div
          role="alert"
          className="max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-8"
        >
          <h1 className="display text-xl font-semibold text-slate-100">
            Unable to check SummitFlow access
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            We couldn’t verify your access. The service may be temporarily
            unavailable, or your connection may have been interrupted.
          </p>
          <Button
            className="mt-4"
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            {isFetching ? 'Checking access...' : 'Try again'}
          </Button>
        </div>
      </div>
    )
  }

  if (!data?.is_owner) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 p-6 text-center">
        <div className="max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-8">
          <h1 className="display text-xl font-semibold text-slate-100">
            You don't have access to SummitFlow
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            SummitFlow is owner-only, and the email you signed in with isn't an
            owner. Sign in with an owner account to continue.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
