'use client'

import { NotesProvider, NotesPanel } from '@summitflow/notes-ui'

export default function NotesPopoutPage() {
  return (
    <NotesProvider apiPrefix="/api" projectScope="summitflow">
      <div className="h-screen flex flex-col bg-slate-950 overflow-hidden relative">
        {/* Atmospheric radial glow */}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: 'radial-gradient(ellipse 80% 60% at 50% 0%, var(--color-slate-800, #1a0a2e) 0%, transparent 70%)',
            opacity: 0.5,
          }}
        />
        {/* Chrome accent line */}
        <div className="chrome-line flex-shrink-0" />
        <NotesPanel />
      </div>
    </NotesProvider>
  )
}
