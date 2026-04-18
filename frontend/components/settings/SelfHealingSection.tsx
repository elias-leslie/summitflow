import { RefreshCw } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

interface SelfHealingSectionProps {
  settings: AutonomousExecutionSettings
  isPending: boolean
  onSelfFixAttemptsChange: (value: string) => void
  onSupervisorAttemptsChange: (value: string) => void
  onExtensionsChange: (value: string) => void
}

export function SelfHealingSection({
  settings,
  isPending,
  onSelfFixAttemptsChange,
  onSupervisorAttemptsChange,
  onExtensionsChange,
}: SelfHealingSectionProps) {
  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
        <RefreshCw className="w-4 h-4 text-slate-400" />
        Self-Healing
      </h3>
      <p className="text-xs text-slate-400">
        Configure retry limits for automatic failure recovery
      </p>

      {/* Self-Fix Attempts */}
      <div>
        <Label
          htmlFor="self-fix-attempts"
          className="text-slate-200 mb-2 block"
        >
          Max Self-Fix Attempts
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          Maximum self-fix attempts before supervisor escalation (0-10)
        </p>
        <Input
          id="self-fix-attempts"
          type="number"
          min={0}
          max={10}
          value={settings.max_self_fix_attempts}
          onChange={(e) => onSelfFixAttemptsChange(e.target.value)}
          disabled={isPending}
          className="max-w-[200px]"
        />
      </div>

      {/* Supervisor Attempts */}
      <div>
        <Label
          htmlFor="supervisor-attempts"
          className="text-slate-200 mb-2 block"
        >
          Max Supervisor Attempts
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          Maximum supervisor-guided attempts before blocking (0-10)
        </p>
        <Input
          id="supervisor-attempts"
          type="number"
          min={0}
          max={10}
          value={settings.max_supervisor_attempts}
          onChange={(e) => onSupervisorAttemptsChange(e.target.value)}
          disabled={isPending}
          className="max-w-[200px]"
        />
      </div>

      {/* Extensions */}
      <div>
        <Label htmlFor="extensions" className="text-slate-200 mb-2 block">
          Max Extensions
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          Maximum extension requests when retry budget exhausted (0-10)
        </p>
        <Input
          id="extensions"
          type="number"
          min={0}
          max={10}
          value={settings.max_extensions}
          onChange={(e) => onExtensionsChange(e.target.value)}
          disabled={isPending}
          className="max-w-[200px]"
        />
      </div>
    </div>
  )
}
