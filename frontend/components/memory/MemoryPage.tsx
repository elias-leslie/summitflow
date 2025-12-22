'use client';

import { Brain } from 'lucide-react';

export default function MemoryPage() {
  return (
    <div className="min-h-screen bg-zinc-900 p-8">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center gap-3 mb-8">
          <Brain className="h-8 w-8 text-purple-400" />
          <h1 className="text-2xl font-semibold text-white">Memory</h1>
        </div>
        <div className="text-zinc-400">
          Memory page placeholder - components coming in tasks 2.2+
        </div>
      </div>
    </div>
  );
}
