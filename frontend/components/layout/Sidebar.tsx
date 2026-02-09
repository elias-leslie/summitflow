'use client'

import { Suspense } from 'react'
import { SidebarContent } from './sidebar/SidebarContent'

export function Sidebar() {
  return (
    <Suspense
      fallback={
        <nav className="w-16 h-full bg-slate-900/50 border-r border-slate-700/50 flex-col hidden md:flex" />
      }
    >
      <SidebarContent />
    </Suspense>
  )
}
