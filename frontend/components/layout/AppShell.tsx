'use client'

import type { ReactNode } from 'react'

interface AppShellProps {
  children: ReactNode
}

/**
 * Application shell - simple wrapper for main content.
 * A-Term is now a standalone app at a-term.summitflow.dev
 */
export function AppShell({ children }: AppShellProps) {
  return <div className="min-w-0 flex-1 overflow-auto">{children}</div>
}
