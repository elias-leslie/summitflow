'use client'

import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect } from 'react'
import { fetchAuthMe } from '@/lib/api/auth'

export function AppAuthGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['auth-me'],
    queryFn: fetchAuthMe,
    retry: false,
  })

  useEffect(() => {
    if (!data?.is_viewer) return
    if (pathname?.startsWith('/viewer')) return
    router.replace('/viewer')
  }, [data?.is_viewer, pathname, router])

  if (isLoading || data?.is_viewer) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-400">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading SummitFlow...
      </div>
    )
  }

  if (isError || !data?.is_owner) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-950 p-6 text-center">
        <div className="max-w-md rounded-2xl border border-slate-800 bg-slate-900/80 p-8">
          <h1 className="display text-xl font-semibold text-slate-100">
            SummitFlow access is not enabled
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Your authenticated email is not an owner. Ask an owner to add your
            account or share a read-only project view.
          </p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
