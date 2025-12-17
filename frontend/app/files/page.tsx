"use client";

import { FileCode2 } from "lucide-react";

export default function FilesPage() {
  return (
    <div className="p-6 space-y-6">
      <header>
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">Files</span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <h1 className="display text-2xl font-semibold text-white">Codebase Analysis</h1>
        <p className="text-slate-400 mt-1">Analyze file structure, LOC, and code quality metrics</p>
      </header>

      <div className="card p-8 text-center">
        <FileCode2 className="w-12 h-12 mx-auto text-slate-600 mb-4" />
        <p className="text-slate-400 mb-2">Select a project to view its files</p>
        <p className="text-sm text-slate-500">File analysis is project-specific. Go to Projects and select one.</p>
      </div>
    </div>
  );
}
