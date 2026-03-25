'use client'

import { NotesProvider, NotesPanel } from '@summitflow/notes-ui'

export default function NotesPopoutPage() {
  return (
    <NotesProvider apiPrefix="/api" projectScope="summitflow">
      <div className="h-screen flex flex-col bg-slate-900 overflow-hidden">
        {/* Phosphor glow line */}
        <div className="h-px w-full flex-shrink-0" style={{
          background: 'linear-gradient(90deg, transparent 0%, var(--color-phosphor-500, #00f5ff) 30%, var(--color-phosphor-400, #33f7ff) 50%, var(--color-phosphor-500, #00f5ff) 70%, transparent 100%)',
          opacity: 0.4,
        }} />
        <NotesPanel />
      </div>
    </NotesProvider>
  )
}
