'use client'

import { CheckCircle, Copy } from 'lucide-react'
import { useState } from 'react'
import { buildApiUrl } from '@/lib/api-config'
import { Button } from '@/components/ui/button'

interface ResumeButtonProps {
  checkpointId: string
  projectId: string
  onResume?: (resumePrompt: string) => void
}

export function ResumeButton({
  checkpointId,
  projectId,
  onResume,
}: ResumeButtonProps) {
  const [copied, setCopied] = useState(false)
  const [resumePrompt, setResumePrompt] = useState<string | null>(null)
  const [loadingPrompt, setLoadingPrompt] = useState(false)

  const fetchResumePrompt = async () => {
    if (resumePrompt) return

    setLoadingPrompt(true)
    try {
      const response = await fetch(
        buildApiUrl(
          `/api/projects/${projectId}/checkpoints/${checkpointId}/resume`,
        ),
        { method: 'POST' },
      )
      if (response.ok) {
        const data = await response.json()
        setResumePrompt(data.resume_prompt)
      }
    } catch (error) {
      console.error('Failed to fetch resume prompt:', error)
    } finally {
      setLoadingPrompt(false)
    }
  }

  const handleCopyPrompt = async () => {
    if (!resumePrompt) {
      await fetchResumePrompt()
    }
    if (resumePrompt) {
      await navigator.clipboard.writeText(resumePrompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      onResume?.(resumePrompt)
    }
  }

  return (
    <Button
      size="sm"
      onClick={handleCopyPrompt}
      disabled={loadingPrompt}
      className="w-full"
    >
      {loadingPrompt ? (
        'Loading...'
      ) : copied ? (
        <>
          <CheckCircle className="h-3.5 w-3.5 mr-1.5" />
          Copied!
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5 mr-1.5" />
          Copy Resume Prompt
        </>
      )}
    </Button>
  )
}
