import clsx from 'clsx'
import { Mic, MicOff, Send } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface TimelineChatInputProps {
  chatEnabled: boolean
  isRecording: boolean
  voiceError: string | null
  onSendMessage: (text: string) => void
  onToggleVoiceRecording: () => void
}

export function TimelineChatInput({
  chatEnabled,
  isRecording,
  voiceError,
  onSendMessage,
  onToggleVoiceRecording,
}: TimelineChatInputProps) {
  const [chatInput, setChatInput] = useState('')
  const [isSending, setIsSending] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!chatInput.trim() || !chatEnabled || isSending) return
    setIsSending(true)
    onSendMessage(chatInput.trim())
    setChatInput('')
    setIsSending(false)
  }

  return (
    <div className="border-t border-slate-700 px-3 py-2">
      {voiceError && (
        <div className="mb-2 text-xs text-amber-400 bg-amber-950/30 px-2 py-1 rounded">
          {voiceError}
        </div>
      )}
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onToggleVoiceRecording}
          disabled={!chatEnabled}
          className={clsx(
            'h-8 px-3 transition-all duration-200',
            isRecording &&
              'bg-red-500/20 border-red-500/50 text-red-400 animate-pulse'
          )}
          title={
            isRecording
              ? 'Stop recording'
              : chatEnabled
                ? 'Start voice input'
                : 'Chat disabled'
          }
        >
          {isRecording ? (
            <MicOff className="h-4 w-4" />
          ) : (
            <Mic className="h-4 w-4" />
          )}
        </Button>

        <Input
          value={chatInput}
          onChange={(e) => setChatInput(e.target.value)}
          placeholder={
            isRecording
              ? 'Recording...'
              : chatEnabled
                ? 'Type or use voice...'
                : 'Chat disabled (not executing)'
          }
          disabled={!chatEnabled || isRecording}
          className="flex-1 h-8 text-sm"
        />

        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={!chatEnabled || !chatInput.trim() || isSending || isRecording}
          className="h-8 px-3"
        >
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  )
}
