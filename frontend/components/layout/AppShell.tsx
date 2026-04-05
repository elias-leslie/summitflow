'use client'

import type { ReactNode } from 'react'

interface AppShellProps {
  children: ReactNode
}

/**
 * Application shell - simple wrapper for main content.
 * A-Term is now a standalone app at aterm.summitflow.dev
 */
export function AppShell({ children }: AppShellProps) {
  return <div className="flex-1 overflow-auto">{children}</div>
}
