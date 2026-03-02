'use client'

import { ApiSpecRenderer } from './ApiSpecRenderer'
import { FileSpecRenderer } from './FileSpecRenderer'
import { GenericSpecRenderer } from './GenericSpecRenderer'
import { PromptSpecRenderer } from './PromptSpecRenderer'
import { detectSpecType } from './SpecRendererTypes'

// Re-export types so existing importers keep working
export type { SpecRecord, SpecType } from './SpecRendererTypes'

/** Main spec renderer that delegates to type-specific renderer */
export function SpecRenderer({
  spec,
}: {
  spec: import('./SpecRendererTypes').SpecRecord
}) {
  const specType = detectSpecType(spec)

  switch (specType) {
    case 'api':
      return <ApiSpecRenderer spec={spec} />
    case 'prompt':
      return <PromptSpecRenderer spec={spec} />
    case 'file':
      return <FileSpecRenderer spec={spec} />
    default:
      return <GenericSpecRenderer spec={spec} />
  }
}
