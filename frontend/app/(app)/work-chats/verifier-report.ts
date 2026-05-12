import type { ChatMessage } from '@agent-hub/chat-ui'

export function latestAssistantContent(messages: ChatMessage[]): string {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message?.role === 'assistant' && message.content.trim()) {
      return message.content
    }
  }
  return ''
}

function extractReportSection(content: string, heading: string): string {
  const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = content.match(
    new RegExp(
      `^###\\s+${escaped}\\s*$([\\s\\S]*?)(?=^###\\s|^##\\s|(?![\\s\\S]))`,
      'im',
    ),
  )
  return match?.[1]?.trim() ?? ''
}

export function parseVerifierReport(content: string): {
  status: string | null
  confidence: string | null
  atomicClaimCount: number | null
  atomicPassCount: number | null
  atomicFailCount: number | null
  feedback: string
  excerpt: string
} {
  const reportIndex = content.search(/^##\s+Report\s*$/im)
  if (reportIndex === -1) {
    return {
      status: null,
      confidence: null,
      atomicClaimCount: null,
      atomicPassCount: null,
      atomicFailCount: null,
      feedback: '',
      excerpt: '',
    }
  }
  const report = content.slice(reportIndex)
  const status = report.match(/^\s*STATUS\s*:\s*([a-z_ -]+)/im)?.[1]?.trim()
  const confidence = report
    .match(/^\s*CONFIDENCE\s*:\s*([a-z_ -]+)/im)?.[1]
    ?.trim()
    .toUpperCase()
  const feedback = extractReportSection(report, 'What feedback did you give?')
  const parseCount = (...patterns: RegExp[]) => {
    for (const pattern of patterns) {
      const match = report.match(pattern)
      if (match?.[1]) return Number.parseInt(match[1], 10)
    }
    return null
  }
  return {
    status: status ?? null,
    confidence: confidence ?? null,
    atomicClaimCount: parseCount(
      /^\s*ATOMIC[_\s-]*CLAIMS?\s*:\s*(\d+)/im,
      /^\s*CLAIMS?\s*:\s*(\d+)/im,
    ),
    atomicPassCount: parseCount(
      /^\s*ATOMIC[_\s-]*PASS(?:ED)?\s*:\s*(\d+)/im,
      /^\s*PASS(?:ED)?\s*:\s*(\d+)/im,
    ),
    atomicFailCount: parseCount(
      /^\s*ATOMIC[_\s-]*FAIL(?:ED)?\s*:\s*(\d+)/im,
      /^\s*FAIL(?:ED)?\s*:\s*(\d+)/im,
    ),
    feedback,
    excerpt: report.slice(0, 5000),
  }
}

export function hasVerifierFeedback(report: {
  status: string | null
  confidence: string | null
  feedback: string
}): boolean {
  if (report.status?.toLowerCase() !== 'failed') return false
  if (report.confidence !== 'FEEDBACK') return false
  const normalized = report.feedback.trim().toLowerCase()
  return Boolean(
    normalized &&
      normalized !== 'none' &&
      normalized !== 'nothing' &&
      normalized !== 'n/a',
  )
}
