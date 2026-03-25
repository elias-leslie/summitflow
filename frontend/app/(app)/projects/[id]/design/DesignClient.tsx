'use client'

import clsx from 'clsx'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { AssetStudioWorkspace } from '@/components/design/AssetStudioWorkspace'
import { UiDesignWorkspace } from '@/components/design/UiDesignWorkspace'

type DesignView = 'ui-design' | 'asset-studio'

export function DesignClient(): React.ReactElement {
  const params = useParams()
  const projectId = params.id as string
  const [activeView, setActiveView] = useState<DesignView>('ui-design')

  return (
    <div className="flex h-full flex-col p-4">
      <section className="mb-6 rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top_left,_rgba(34,211,238,0.18),_transparent_30%),radial-gradient(circle_at_80%_20%,_rgba(251,146,60,0.16),_transparent_24%),linear-gradient(180deg,#020617,#0f172a)] p-6 shadow-[0_20px_80px_rgba(2,6,23,0.35)]">
        <p className="text-xs uppercase tracking-[0.24em] text-cyan-300">Design Ops</p>
        <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <h1 className="text-3xl font-bold tracking-tight text-slate-100 display">
              A design workspace for UI review and asset production
            </h1>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Shift between page-level UI analysis and a production-oriented asset studio for sprites,
              mockups, environments, iconography, and exportable sheets.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveView('ui-design')}
              className={clsx('rounded-full px-4 py-2 text-sm font-medium transition-all duration-200',
                activeView === 'ui-design'
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30 shadow-[0_0_12px_rgba(0,245,255,0.15)]'
                  : 'bg-slate-900/70 text-slate-400 border border-slate-700 hover:text-slate-200 hover:border-slate-600'
              )}
            >
              UI Design
            </button>
            <button
              type="button"
              onClick={() => setActiveView('asset-studio')}
              className={clsx('rounded-full px-4 py-2 text-sm font-medium transition-all duration-200',
                activeView === 'asset-studio'
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30 shadow-[0_0_12px_rgba(0,245,255,0.15)]'
                  : 'bg-slate-900/70 text-slate-400 border border-slate-700 hover:text-slate-200 hover:border-slate-600'
              )}
            >
              Asset Studio
            </button>
          </div>
        </div>
      </section>

      {activeView === 'ui-design' ? (
        <UiDesignWorkspace projectId={projectId} />
      ) : (
        <AssetStudioWorkspace projectId={projectId} />
      )}
    </div>
  )
}
