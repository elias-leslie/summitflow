'use client'

export default function SettingsPage() {
  return (
    <div className="p-6 space-y-6">
      <header>
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">
            Settings
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <h1 className="display text-2xl font-semibold text-white">
          Platform Settings
        </h1>
        <p className="text-slate-400 mt-1">Configure SummitFlow preferences</p>
      </header>

      <div className="card p-6 space-y-4">
        <h2 className="font-semibold text-white">General</h2>
        <div className="space-y-3">
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <div>
              <p className="text-sm text-slate-300">Theme</p>
              <p className="text-xs text-slate-500">
                Dark mode is currently the only option
              </p>
            </div>
            <span className="text-sm text-slate-400">Dark</span>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-slate-800">
            <div>
              <p className="text-sm text-slate-300">API Endpoint</p>
              <p className="text-xs text-slate-500">Backend service URL</p>
            </div>
            <span className="text-sm text-slate-400 mono">localhost:8001</span>
          </div>
        </div>
      </div>

      <div className="card p-6 space-y-4">
        <h2 className="font-semibold text-white">About</h2>
        <div className="space-y-2 text-sm">
          <p className="text-slate-400">SummitFlow v0.1.0</p>
          <p className="text-slate-500">
            AI-assisted software development platform
          </p>
        </div>
      </div>
    </div>
  )
}
