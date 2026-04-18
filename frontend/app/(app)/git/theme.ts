// Design System Tokens (Stitch "Outrun" Theme)
export const THEME = {
  colors: {
    void: 'bg-[#0a0612]', // Deep Void
    card: 'bg-gradient-to-br from-slate-900 to-[#0f0a18]', // Elevated Surface
    border: 'border-slate-800',
    borderGlow:
      'hover:border-pink-500/30 hover:shadow-[0_0_15px_rgba(255,0,102,0.15)]',
    text: {
      primary: 'text-slate-200',
      secondary: 'text-slate-500',
      header: 'font-display tracking-tight text-slate-100',
      mono: 'font-mono text-cyan-400',
    },
    accent: {
      pink: 'text-[#ff0066]',
      cyan: 'text-[#00f5ff]',
      amber: 'text-amber-400',
    },
  },
} as const
