'use client'

import { Info, MessageSquare } from 'lucide-react'
import Link from 'next/link'
import { NotificationBell } from '@/components/notifications'
import { GlobalAutoExecDropdown } from './GlobalAutoExecDropdown'
import { AnimatedLogo } from './topbar/AnimatedLogo'
import { Navigation } from './topbar/Navigation'
import { TaskSearch } from './topbar/TaskSearch'
import { SUMMITFLOW_PROJECT_ID } from './topbar/constants'

export function TopBar() {
  return (
    <>
      <header className="h-16 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-4">
        <AnimatedLogo />
        <Navigation />
        <div className="flex-1" />
        <GlobalAutoExecDropdown />
        <TaskSearch />
        <div className="flex items-center gap-1 flex-shrink-0">
          <Link
            href="/chat"
            className="lg:hidden p-2.5 rounded-lg text-phosphor-400 hover:bg-phosphor-500/10 hover:text-phosphor-300 transition-all duration-200"
            title="Johnny"
          >
            <MessageSquare className="w-5 h-5" />
          </Link>
          <Link
            href="/about"
            data-testid="topbar-about"
            className="p-2.5 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="About SummitFlow"
          >
            <Info className="w-5 h-5" />
          </Link>
          <NotificationBell projectId={SUMMITFLOW_PROJECT_ID} />
        </div>
      </header>
      <div className="chrome-line" />
    </>
  )
}
