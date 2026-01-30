import type { ConceptCardProps } from './types'

const colors = {
  orange: {
    bg: 'rgba(255, 102, 0, 0.1)',
    border: 'rgba(255, 102, 0, 0.2)',
    text: '#ff6600',
  },
  pink: {
    bg: 'rgba(255, 0, 102, 0.1)',
    border: 'rgba(255, 0, 102, 0.2)',
    text: '#ff0066',
  },
  cyan: {
    bg: 'rgba(0, 245, 255, 0.1)',
    border: 'rgba(0, 245, 255, 0.2)',
    text: '#00f5ff',
  },
}

export function ConceptCard({
  icon,
  title,
  description,
  color,
}: ConceptCardProps): React.ReactElement {
  const c = colors[color]

  return (
    <div
      className="p-6 rounded-xl border transition-all hover:scale-[1.02]"
      style={{
        background: c.bg,
        borderColor: c.border,
      }}
    >
      <div
        className="w-12 h-12 rounded-lg flex items-center justify-center mb-4"
        style={{ color: c.text, background: `${c.bg}` }}
      >
        {icon}
      </div>
      <h3 className="display text-lg font-semibold text-white mb-2">{title}</h3>
      <p className="text-slate-400 text-sm leading-relaxed">{description}</p>
    </div>
  )
}
