import { clsx } from 'clsx'
import { Shield } from 'lucide-react'
import type { AutonomousExecutionSettings } from '@/lib/api'
import { Label } from '../ui/label'

const QUALITY_TOOLS = [
  { value: 'pytest', label: 'pytest', description: 'Tests' },
  { value: 'ruff', label: 'ruff', description: 'Lint' },
  { value: 'mypy', label: 'mypy', description: 'Types' },
  { value: 'biome', label: 'biome', description: 'Frontend lint' },
  { value: 'tsc', label: 'tsc', description: 'TypeScript' },
  { value: 'sqlfluff', label: 'sqlfluff', description: 'SQL lint' },
  { value: 'squawk', label: 'squawk', description: 'Migration lint' },
]

const QUALITY_MODES = [
  { value: 'quick', label: 'Quick', description: 'Fast subset of checks' },
  { value: 'check', label: 'Full Check', description: 'All checks, all files' },
  { value: 'changed-only', label: 'Changed Only', description: 'Only changed files' },
]

interface QualityGateSectionProps {
  settings: AutonomousExecutionSettings
  isPending: boolean
  onToolsChange: (tools: string[]) => void
  onModeChange: (mode: string) => void
  onFixEnabledToggle: () => void
}

export function QualityGateSection({
  settings,
  isPending,
  onToolsChange,
  onModeChange,
  onFixEnabledToggle,
}: QualityGateSectionProps) {
  const selectedTools = settings.quality_gate_tools ?? []
  const useCustomTools = selectedTools.length > 0

  const handleToolToggle = (tool: string) => {
    const newTools = selectedTools.includes(tool)
      ? selectedTools.filter(t => t !== tool)
      : [...selectedTools, tool]
    onToolsChange(newTools)
  }

  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
        <Shield className="w-4 h-4 text-slate-400" />
        Quality Gates
      </h3>
      <p className="text-xs text-slate-400">
        Configure which quality checks run during autonomous execution
      </p>

      {/* Mode Selector (only shown when no custom tools selected) */}
      {!useCustomTools && (
        <div>
          <Label className="text-slate-200 mb-3 block">Gate Mode</Label>
          <div className="flex gap-2">
            {QUALITY_MODES.map(mode => (
              <button
                type="button"
                key={mode.value}
                onClick={() => onModeChange(mode.value)}
                disabled={isPending}
                className={clsx(
                  'px-3 py-2 rounded-lg text-xs font-medium transition-colors border',
                  settings.quality_gate_mode === mode.value
                    ? 'bg-phosphor-500/20 border-phosphor-500/50 text-phosphor-300'
                    : 'bg-slate-700/50 border-slate-600 text-slate-300 hover:bg-slate-700',
                )}
              >
                <div>{mode.label}</div>
                <div className="text-[10px] opacity-70 mt-0.5">{mode.description}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Tool Selection */}
      <div>
        <Label className="text-slate-200 mb-2 block">
          {useCustomTools ? 'Selected Tools' : 'Custom Tool Selection'}
        </Label>
        <p className="text-xs text-slate-400 mb-3">
          {useCustomTools
            ? 'Only these tools will run. Clear all to use the mode above.'
            : 'Select specific tools to override the mode above.'}
        </p>
        <div className="flex flex-wrap gap-2">
          {QUALITY_TOOLS.map(tool => (
            <button
              type="button"
              key={tool.value}
              onClick={() => handleToolToggle(tool.value)}
              disabled={isPending}
              className={clsx(
                'px-3 py-1.5 rounded-md text-xs font-medium transition-colors border',
                selectedTools.includes(tool.value)
                  ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-300'
                  : 'bg-slate-700/50 border-slate-600 text-slate-400 hover:text-slate-300 hover:bg-slate-700',
              )}
            >
              {tool.label}
              <span className="ml-1 opacity-60">({tool.description})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Auto-Fix Toggle */}
      <div>
        <div className="flex items-center justify-between">
          <div>
            <Label className="text-slate-200 block">Auto-Fix Enabled</Label>
            <p className="text-xs text-slate-400 mt-1">
              Allow dt --fix during self-healing to auto-format and lint-fix
            </p>
          </div>
          <button
            type="button"
            onClick={onFixEnabledToggle}
            disabled={isPending}
            aria-label={settings.quality_gate_fix_enabled ? 'Disable auto-fix' : 'Enable auto-fix'}
            className={clsx(
              'relative w-12 h-6 rounded-full transition-colors',
              settings.quality_gate_fix_enabled ? 'bg-phosphor-500' : 'bg-slate-600',
            )}
          >
            <span
              className={clsx(
                'absolute top-1 w-4 h-4 bg-white rounded-full transition-transform',
                settings.quality_gate_fix_enabled ? 'translate-x-7' : 'translate-x-1',
              )}
            />
          </button>
        </div>
      </div>
    </div>
  )
}
