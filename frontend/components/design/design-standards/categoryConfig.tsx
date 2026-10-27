/**
 * Category configuration for design standards
 */

import {
  Component,
  Droplet,
  Info,
  Layout,
  Navigation,
  Type,
} from 'lucide-react'

export const categoryConfig: Record<
  string,
  { icon: React.ReactNode; color: string; label: string }
> = {
  layout: {
    icon: <Layout className="w-4 h-4" />,
    color: 'text-cyan-400',
    label: 'Layout',
  },
  typography: {
    icon: <Type className="w-4 h-4" />,
    color: 'text-violet-400',
    label: 'Typography',
  },
  color: {
    icon: <Droplet className="w-4 h-4" />,
    color: 'text-pink-400',
    label: 'Color',
  },
  components: {
    icon: <Component className="w-4 h-4" />,
    color: 'text-amber-400',
    label: 'Components',
  },
  navigation: {
    icon: <Navigation className="w-4 h-4" />,
    color: 'text-emerald-400',
    label: 'Navigation',
  },
}

export const defaultCategoryConfig = {
  icon: <Info className="w-4 h-4" />,
  color: 'text-slate-400',
  label: 'Unknown',
}
