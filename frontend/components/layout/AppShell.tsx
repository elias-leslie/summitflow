'use client'

import type { ReactNode } from 'react'

interface AppShellProps {
  children: ReactNode
}

/**
 * Application shell - fills the space below the top bar so the sidebar and
 * full-height pages (files, graph) get the viewport height, not their content's.
 */
export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      {children}
    </div>
  )
}
