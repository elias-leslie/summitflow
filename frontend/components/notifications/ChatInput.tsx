import { clsx } from 'clsx'
import { Send } from 'lucide-react'
import { useState } from 'react'

interface ChatInputProps {
  onSend: (message: string) => void
  disabled: boolean
}

export function ChatInput({ onSend, disabled }: ChatInputProps) {
  const [userInput, setUserInput] = useState('')

  const handleSend = () => {
    if (!userInput.trim() || disabled) return
    onSend(userInput)
    setUserInput('')
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-4 border-t border-slate-700 bg-slate-900/50">
      <div className="flex gap-2">
        <textarea
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Describe what you'd like me to try..."
          className="flex-1 p-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 resize-none focus:outline-none focus:ring-1 focus:ring-phosphor-500"
          rows={2}
        />
        <button
          onClick={handleSend}
          disabled={!userInput.trim() || disabled}
          className={clsx(
            'p-3 rounded-lg transition-colors',
            userInput.trim() && !disabled
              ? 'bg-phosphor-500 text-white hover:bg-phosphor-600'
              : 'bg-slate-700 text-slate-500 cursor-not-allowed',
          )}
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
      <p className="text-xs text-slate-600 mt-2">
        Press Enter to send, Shift+Enter for new line
      </p>
    </div>
  )
}
