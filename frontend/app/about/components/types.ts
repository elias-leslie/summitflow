export type TabId = 'overview' | 'how-it-works' | 'getting-started' | 'features'

export interface Tab {
  id: TabId
  label: string
  icon: React.ReactNode
}

export interface ConceptCardProps {
  icon: React.ReactNode
  title: string
  description: string
  color: 'orange' | 'pink' | 'cyan'
}

export interface FeatureCardProps {
  icon: React.ReactNode
  title: string
  description: string
  color: string
}

export interface ScreenshotPlaceholderProps {
  label: string
  description: string
  dark?: boolean
}
