import { AlertTriangle, Check } from 'lucide-react'

interface ToastProps {
  message: string
  type: 'success' | 'error'
}

export function Toast({ message, type }: ToastProps) {
  return (
    <div
      className={`fixed top-4 right-4 z-50 px-4 py-2 rounded-lg shadow-lg flex items-center gap-2 ${
        type === 'success'
          ? 'bg-emerald-500/20 border border-emerald-500/50 text-emerald-400'
          : 'bg-rose-500/20 border border-rose-500/50 text-rose-400'
      }`}
    >
      {type === 'success' ? (
        <Check className="w-4 h-4" />
      ) : (
        <AlertTriangle className="w-4 h-4" />
      )}
      {message}
    </div>
  )
}
