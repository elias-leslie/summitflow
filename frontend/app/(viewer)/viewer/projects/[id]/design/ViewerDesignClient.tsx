'use client'

import clsx from 'clsx'
import { ArrowLeft, Eye, Palette } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { AssetStudioWorkspace } from '@/components/design/AssetStudioWorkspace'
import { UiDesignWorkspace } from '@/components/design/UiDesignWorkspace'

type DesignView = 'ui-design' | 'asset-studio'

export function ViewerDesignClient(): React.ReactElement {
  const params = useParams<{ id: string }>()
  const projectId = params.id
  const [activeView, setActiveView] = useState<DesignView>('ui-design')

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex-none border-b border-slate-800 bg-slate-950/80 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Link
              href="/viewer"
              className="rounded-lg border border-slate-800 p-2 text-slate-400 transition hover:text-slate-100"
              aria-label="Back to shared projects"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div className="rounded-2xl bg-fuchsia-500/10 p-2 ring-1 ring-fuchsia-400/20">
              <Palette className="h-5 w-5 text-fuchsia-300" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="display truncate text-lg font-semibold text-slate-100">
                  {projectId}
                </h1>
                <span className="rounded-full border border-blue-500/20 bg-blue-500/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] text-blue-200">
                  <Eye className="mr-1 inline h-3 w-3" />
                  Read only
                </span>
              </div>
              <p className="mt-0.5 text-xs text-slate-500">
                Shared Design section
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveView('ui-design')}
              className={clsx(
                'rounded-full px-4 py-2 text-sm font-medium transition-all duration-200',
                activeView === 'ui-design'
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30'
                  : 'bg-slate-900/70 text-slate-400 border border-slate-700 hover:text-slate-200 hover:border-slate-600',
              )}
            >
              UI Design
            </button>
            <button
              type="button"
              onClick={() => setActiveView('asset-studio')}
              className={clsx(
                'rounded-full px-4 py-2 text-sm font-medium transition-all duration-200',
                activeView === 'asset-studio'
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30'
                  : 'bg-slate-900/70 text-slate-400 border border-slate-700 hover:text-slate-200 hover:border-slate-600',
              )}
            >
              Asset Studio
            </button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-auto p-4">
        {activeView === 'ui-design' ? (
          <UiDesignWorkspace projectId={projectId} readOnly />
        ) : (
          <AssetStudioWorkspace projectId={projectId} readOnly />
        )}
      </main>
    </div>
  )
}
