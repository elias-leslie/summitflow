'use client'

import { Camera } from 'lucide-react'

export default function EvidencePage() {
  return (
    <div className="p-6 space-y-6">
      <header>
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">
            Evidence
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <h1 className="display text-2xl font-semibold text-white">
          Verification Evidence
        </h1>
        <p className="text-slate-400 mt-1">
          Screenshots and verification artifacts for features
        </p>
      </header>

      <div className="card p-8 text-center">
        <Camera className="w-12 h-12 mx-auto text-slate-600 mb-4" />
        <p className="text-slate-400 mb-2">
          Select a project to view its evidence
        </p>
        <p className="text-sm text-slate-500">
          Evidence is captured per-feature. Go to Projects and select one.
        </p>
      </div>
    </div>
  )
}
