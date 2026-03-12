import { Layers, Sparkles, Workflow, Zap } from 'lucide-react'
import { motion } from 'motion/react'

import type { Tab, TabId } from './types'

const tabs: Tab[] = [
  { id: 'overview', label: 'Overview', icon: <Layers className="w-4 h-4" /> },
  {
    id: 'how-it-works',
    label: 'How It Works',
    icon: <Workflow className="w-4 h-4" />,
  },
  {
    id: 'getting-started',
    label: 'Getting Started',
    icon: <Zap className="w-4 h-4" />,
  },
  { id: 'features', label: 'Features', icon: <Sparkles className="w-4 h-4" /> },
]

interface TabNavigationProps {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
}

export function TabNavigation({
  activeTab,
  onTabChange,
}: TabNavigationProps): React.ReactElement {
  return (
    <section className="sticky top-0 z-20 bg-slate-950/95 backdrop-blur-sm border-b border-slate-800">
      <div className="max-w-6xl mx-auto px-8">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              type="button"
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`
                relative px-5 py-4 flex items-center gap-2 text-sm font-medium transition-colors
                ${
                  activeTab === tab.id
                    ? 'text-white'
                    : 'text-slate-500 hover:text-slate-300'
                }
              `}
            >
              {tab.icon}
              {tab.label}
              {activeTab === tab.id && (
                <motion.div
                  layoutId="about-tab-indicator"
                  className="absolute bottom-0 left-0 right-0 h-0.5"
                  style={{
                    background:
                      'linear-gradient(90deg, #ff6600 0%, #ff0066 100%)',
                  }}
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
            </button>
          ))}
        </nav>
      </div>
    </section>
  )
}
