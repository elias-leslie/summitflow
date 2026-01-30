'use client'

import { AnimatePresence } from 'motion/react'
import { useState } from 'react'

import {
  FeaturesTab,
  FooterCTA,
  GettingStartedTab,
  HeroSection,
  HowItWorksTab,
  OverviewTab,
  TabNavigation,
} from './components'
import type { TabId } from './components'

export default function AboutPage(): React.ReactElement {
  const [activeTab, setActiveTab] = useState<TabId>('overview')

  return (
    <div className="min-h-full overflow-auto">
      <HeroSection />

      <TabNavigation activeTab={activeTab} onTabChange={setActiveTab} />

      <section className="max-w-6xl mx-auto px-8 py-12">
        <AnimatePresence mode="wait">
          {activeTab === 'overview' && <OverviewTab key="overview" />}
          {activeTab === 'how-it-works' && <HowItWorksTab key="how-it-works" />}
          {activeTab === 'getting-started' && (
            <GettingStartedTab key="getting-started" />
          )}
          {activeTab === 'features' && <FeaturesTab key="features" />}
        </AnimatePresence>
      </section>

      <FooterCTA />
    </div>
  )
}
