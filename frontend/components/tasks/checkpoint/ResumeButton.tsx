'use client'

import { CheckCircle, Copy } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
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

  const fetchResumePrompt = async (): Promise<string | null> => {
    if (resumePrompt) {
      return resumePrompt
    }

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
        return data.resume_prompt
      }
      toast.error('Failed to load resume prompt')
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to load resume prompt',
      )
    } finally {
      setLoadingPrompt(false)
    }

    return null
  }

  const handleCopyPrompt = async () => {
    const prompt = resumePrompt ?? (await fetchResumePrompt())
    if (!prompt) {
      return
    }

    try {
      await navigator.clipboard.writeText(prompt)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      onResume?.(prompt)
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Failed to copy resume prompt',
      )
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
