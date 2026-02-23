// Utility functions for autonomous settings

export const TASK_TYPES = [
  { value: 'refactor', label: 'Refactor' },
  { value: 'bug', label: 'Bug' },
  { value: 'feature', label: 'Feature' },
  { value: 'chore', label: 'Chore' },
  { value: 'docs', label: 'Docs' },
]

export const MODEL_TIERS = [
  { value: 'standard', label: 'Standard', description: 'Balanced performance and cost' },
  { value: 'advanced', label: 'Advanced', description: 'Higher capability, higher cost' },
  { value: 'economy', label: 'Economy', description: 'Cost-optimized for simple tasks' },
]
