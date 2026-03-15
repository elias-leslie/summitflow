'use client'

import { HardDrive, ArrowRight } from 'lucide-react'
import Link from 'next/link'

interface SetupPromptProps {
  inline?: boolean
}

export function SetupPrompt({ inline }: SetupPromptProps) {
  if (inline) {
    return (
      <div className="p-4 bg-phosphor-600/10 rounded-lg border border-phosphor-500/30">
        <p className="text-sm text-slate-300 mb-3">
          No storage backend configured. Set one up to protect your backups.
        </p>
        <Link
          href="/backups/setup"
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-phosphor-600 text-white rounded-md text-sm font-medium hover:bg-phosphor-500 transition-colors"
        >
          Set up storage
          <ArrowRight className="w-4 h-4" />
        </Link>
      </div>
    )
  }

  return (
    <div className="mb-8 p-6 bg-gradient-to-r from-phosphor-600/10 to-blue-600/10 rounded-lg border border-phosphor-500/30">
      <div className="flex items-start gap-4">
        <div className="p-3 bg-phosphor-500/20 rounded-lg shrink-0">
          <HardDrive className="w-6 h-6 text-phosphor-400" />
        </div>
        <div className="flex-1">
          <h3 className="text-lg font-medium text-slate-100 mb-1">
            Set up backup storage
          </h3>
          <p className="text-sm text-slate-400 mb-4">
            Configure where your backups are stored to protect your data.
            Backups will be sent to your NAS or file server automatically.
          </p>
          <Link
            href="/backups/setup"
            className="inline-flex items-center gap-2 px-4 py-2 bg-phosphor-600 text-white rounded-md
                       text-sm font-medium hover:bg-phosphor-500 transition-colors"
          >
            Set up storage
            <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </div>
    </div>
  )
}
