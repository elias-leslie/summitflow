import { clsx } from 'clsx'

interface ConfirmStepProps {
  projectName: string
  confirmText: string
  onConfirmTextChange: (text: string) => void
}

export function ConfirmStep({
  projectName,
  confirmText,
  onConfirmTextChange,
}: ConfirmStepProps) {
  const isConfirmValid = confirmText === projectName

  return (
    <div className="space-y-4">
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
        <p className="text-sm text-red-300">
          <strong>Final Confirmation Required</strong>
          <br />
          To proceed, type the project name below:
        </p>
        <p className="mt-2 text-lg font-mono text-red-400 text-center">
          {projectName}
        </p>
      </div>

      <div>
        <label
          htmlFor="confirm-project-name"
          className="block text-sm font-medium text-slate-300 mb-2"
        >
          Type project name to confirm
        </label>
        <input
          id="confirm-project-name"
          type="text"
          value={confirmText}
          onChange={(e) => onConfirmTextChange(e.target.value)}
          placeholder={projectName}
          className={clsx(
            'w-full px-3 py-2 bg-slate-700 border rounded-md text-slate-200',
            'placeholder-slate-500 focus:outline-none focus:ring-2',
            isConfirmValid
              ? 'border-green-500 focus:ring-green-500'
              : 'border-slate-600 focus:ring-phosphor-500',
          )}
          autoComplete="off"
        />
        {confirmText && !isConfirmValid && (
          <p className="mt-1 text-xs text-red-400">
            Text does not match project name
          </p>
        )}
      </div>
    </div>
  )
}
