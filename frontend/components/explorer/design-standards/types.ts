/**
 * Type definitions for design standards
 */

export interface RequirementValue {
  exact?: string | number | boolean
  min?: number
  max?: number
  allowed?: (string | number)[]
  severity: 'error' | 'warning' | 'info'
}

export interface DesignRule {
  id: number
  standard_id: number
  category: string
  rule_id: string
  name: string
  requirements: Record<string, RequirementValue>
  created_at: string
  source: string | null
}

export interface DesignStandardsPanelProps {
  projectId: string
  className?: string
}
