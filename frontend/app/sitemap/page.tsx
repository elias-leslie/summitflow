"use client";

import { Map } from "lucide-react";

export default function SitemapPage() {
  return (
    <div className="p-6 space-y-6">
      <header>
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">Sitemap</span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <h1 className="display text-2xl font-semibold text-white">API & Route Discovery</h1>
        <p className="text-slate-400 mt-1">Discover and monitor API endpoints and frontend routes</p>
      </header>

      <div className="card p-8 text-center">
        <Map className="w-12 h-12 mx-auto text-slate-600 mb-4" />
        <p className="text-slate-400 mb-2">Select a project to view its sitemap</p>
        <p className="text-sm text-slate-500">Sitemap discovery is project-specific. Go to Projects and select one.</p>
      </div>
    </div>
  );
}
