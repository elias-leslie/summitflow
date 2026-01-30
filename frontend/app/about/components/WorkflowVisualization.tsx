import { ArrowRight } from 'lucide-react'

const states = [
  { name: 'Pending', color: '#64748b' },
  { name: 'Ready', color: '#00f5ff' },
  { name: 'Running', color: '#ff6600' },
  { name: 'Completed', color: '#00ff88' },
]

export function WorkflowVisualization(): React.ReactElement {
  return (
    <div className="flex items-center justify-center gap-4 flex-wrap">
      {states.map((state, i) => (
        <div key={state.name} className="flex items-center gap-4">
          <div
            className="px-6 py-3 rounded-lg border text-sm font-medium"
            style={{
              borderColor: `${state.color}40`,
              background: `${state.color}10`,
              color: state.color,
            }}
          >
            {state.name}
          </div>
          {i < states.length - 1 && (
            <ArrowRight className="w-5 h-5 text-slate-600" />
          )}
        </div>
      ))}
    </div>
  )
}
