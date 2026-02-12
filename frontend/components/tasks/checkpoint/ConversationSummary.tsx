'use client'

import { ChevronDown, ChevronUp, MessageSquare } from 'lucide-react'
import { useState } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'

interface ConversationSummaryProps {
  summary: string
}

export function ConversationSummary({ summary }: ConversationSummaryProps) {
  const [showSummary, setShowSummary] = useState(false)

  return (
    <div className="space-y-1">
      <button
        onClick={() => setShowSummary(!showSummary)}
        className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
      >
        <MessageSquare className="h-3.5 w-3.5" />
        Conversation Summary
        {showSummary ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
      </button>
      {showSummary && (
        <ScrollArea className="max-h-40 rounded border border-slate-200 dark:border-slate-700 p-2">
          <pre className="text-xs whitespace-pre-wrap text-slate-600 dark:text-slate-400">
            {summary}
          </pre>
        </ScrollArea>
      )}
    </div>
  )
}
