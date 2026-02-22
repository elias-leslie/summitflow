import { Suspense } from 'react'
import { PersonaChatClient } from './PersonaChatClient'

export const metadata = {
  title: 'Persona Chat — SummitFlow',
}

function ChatLoading() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-600">
      <div className="w-6 h-6 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
      <span className="text-xs font-mono">Connecting…</span>
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense fallback={<ChatLoading />}>
      <PersonaChatClient />
    </Suspense>
  )
}
