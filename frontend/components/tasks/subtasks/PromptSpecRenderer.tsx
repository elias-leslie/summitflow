'use client'

import { MessageSquareQuote } from 'lucide-react'
import { getSpecValue, type SpecRecord } from './SpecRendererTypes'

/** Highlight template variables in text ({{var}} or {var} patterns) */
function HighlightTemplateVars({ text }: { text: string }) {
  // Match both {{var}} and {var} patterns
  const parts = text.split(/(\{\{?\w+\}?\})/g)

  return (
    <>
      {parts.map((part, i) => {
        if (part.match(/^\{\{?\w+\}?\}$/)) {
          return (
            <span key={`var-${i}-${part}`} className="text-purple-400 font-semibold">
              {part}
            </span>
          )
        }
        return <span key={`text-${i}-${part.slice(0, 8)}`}>{part}</span>
      })}
    </>
  )
}

/** Prompt spec renderer with quoted text and variable highlighting */
export function PromptSpecRenderer({ spec }: { spec: SpecRecord }) {
  const promptFields = [
    'prompt',
    'template',
    'message',
    'system',
    'user',
    'assistant',
  ]
  const mainPrompt = getSpecValue(spec, promptFields) || undefined

  const otherFields = Object.entries(spec).filter(
    ([key]) => !promptFields.includes(key.toLowerCase()),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <MessageSquareQuote className="w-3.5 h-3.5 text-purple-400 mt-0.5 flex-shrink-0" />
        <div className="flex-1">
          {mainPrompt ? (
            <blockquote className="text-xs text-slate-300 italic border-l-2 border-purple-500/40 pl-3 py-1 bg-purple-500/5 rounded-r">
              <HighlightTemplateVars text={mainPrompt} />
            </blockquote>
          ) : (
            <span className="text-2xs text-slate-500">(no prompt text)</span>
          )}
        </div>
      </div>
      {otherFields.length > 0 && (
        <div className="pl-5 space-y-1">
          {otherFields.map(([key, value]) => (
            <div key={key} className="flex gap-2 text-2xs">
              <span className="text-slate-500 font-mono">{key}:</span>
              <span className="text-amber-300/80">
                {typeof value === 'string' ? (
                  <HighlightTemplateVars text={value} />
                ) : (
                  JSON.stringify(value)
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
