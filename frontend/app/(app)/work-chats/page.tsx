'use client'

import { Suspense } from 'react'
import { WorkChatsContent } from './work-chats-content'

export default function WorkChatsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[calc(100dvh-66px)] items-center justify-center text-sm text-slate-500 lg:h-[calc(100dvh-70px)]">
          Loading...
        </div>
      }
    >
      <WorkChatsContent />
    </Suspense>
  )
}
