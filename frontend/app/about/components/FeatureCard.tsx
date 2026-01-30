import type { FeatureCardProps } from './types'

const colorMap: Record<string, string> = {
  orange: '#ff6600',
  pink: '#ff0066',
  cyan: '#00f5ff',
  yellow: '#fff200',
  purple: '#bf00ff',
  green: '#00ff88',
}

export function FeatureCard({
  icon,
  title,
  description,
  color,
}: FeatureCardProps): React.ReactElement {
  const c = colorMap[color] || colorMap.orange

  return (
    <div className="p-6 rounded-xl border border-slate-800 bg-slate-900/50 hover:bg-slate-900 transition-colors group">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center mb-4 transition-transform group-hover:scale-110"
        style={{
          color: c,
          background: `${c}15`,
          border: `1px solid ${c}30`,
        }}
      >
        {icon}
      </div>
      <h3 className="display text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
    </div>
  )
}
