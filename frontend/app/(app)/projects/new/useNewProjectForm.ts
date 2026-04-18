'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import type { ProjectCategory } from '@/lib/api'
import { createProject } from '@/lib/api'
import {
  buildHealthPreview,
  buildManagedRootPath,
  DEFAULT_HEALTH_ENDPOINT,
  isManagedWorkspaceRootPath,
  normalizeProjectFormValues,
  normalizeProjectId,
  normalizeRootPath,
  type ProjectFormErrors,
  validateProjectForm,
} from '@/lib/project-registration'
import {
  DEFAULT_ONBOARDING,
  DEFAULT_PERMISSION_TIER,
  EXECUTION_END_HOUR,
  EXECUTION_START_HOUR,
  QUERY_KEYS,
  ROUTE_PROJECT,
} from './constants'

type FormErrors = ProjectFormErrors & { submit?: string }
type ErrorField = keyof FormErrors

export type { FormErrors }

export function useNewProjectForm() {
  const router = useRouter()
  const queryClient = useQueryClient()

  const [name, setName] = useState('')
  const [projectId, setProjectId] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [healthEndpoint, setHealthEndpoint] = useState(DEFAULT_HEALTH_ENDPOINT)
  const [rootPath, setRootPath] = useState('')
  const [category, setCategory] = useState<ProjectCategory>('dev')
  const [syncAgentHubPermission, setSyncAgentHubPermission] = useState(true)
  const [permissionTier, setPermissionTier] = useState(DEFAULT_PERMISSION_TIER)
  const [autoExecEnabled, setAutoExecEnabled] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projects })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.projectsWithStats })
      router.push(ROUTE_PROJECT(project.id))
    },
    onError: (error: Error) => {
      setErrors({ submit: error.message })
    },
  })

  const clearError = (field: ErrorField) => {
    setErrors((current) => {
      if (!(field in current) && !('submit' in current)) {
        return current
      }
      const next = { ...current }
      delete next[field]
      delete next.submit
      return next
    })
  }

  const syncManagedDefaults = (
    nextProjectId: string,
    previousProjectId: string,
  ) => {
    const previousRootPath = buildManagedRootPath(previousProjectId)
    const nextRootPath = buildManagedRootPath(nextProjectId)
    setProjectId(nextProjectId)
    setRootPath((current) =>
      !current || current === previousRootPath ? nextRootPath : current,
    )
  }

  const handleNameChange = (value: string) => {
    clearError('name')
    setName(value)
    if (!projectId || projectId === normalizeProjectId(name)) {
      syncManagedDefaults(normalizeProjectId(value), projectId)
    }
  }

  const handleProjectIdChange = (value: string) => {
    clearError('projectId')
    syncManagedDefaults(normalizeProjectId(value), projectId)
  }

  const handleBaseUrlChange = (value: string) => {
    clearError('baseUrl')
    setBaseUrl(value)
  }

  const handleHealthEndpointChange = (value: string) => {
    clearError('healthEndpoint')
    setHealthEndpoint(value)
  }

  const handleRootPathChange = (value: string) => {
    clearError('rootPath')
    setRootPath(value)
  }

  const handleCategoryChange = (value: ProjectCategory) => {
    setCategory(value)
  }

  const validate = (): boolean => {
    const newErrors = validateProjectForm({
      name,
      projectId,
      baseUrl,
      healthEndpoint,
      rootPath,
    })
    if (isManagedWorkspaceRootPath(rootPath) && !baseUrl.trim()) {
      delete newErrors.baseUrl
    }
    setErrors(newErrors)

    if (Object.keys(newErrors).length === 0) {
      const normalized = normalizeProjectFormValues({
        name,
        projectId,
        baseUrl,
        healthEndpoint,
        rootPath,
      })
      setProjectId(normalized.projectId ?? '')
      setBaseUrl(normalized.baseUrl)
      setHealthEndpoint(normalized.healthEndpoint)
      setRootPath(normalized.rootPath)
    }

    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    const normalized = normalizeProjectFormValues({
      name,
      projectId,
      baseUrl,
      healthEndpoint,
      rootPath,
    })
    const summitflowHosted = isManagedWorkspaceRootPath(normalized.rootPath)

    mutation.mutate({
      id: normalized.projectId ?? '',
      name: normalized.name,
      base_url: normalized.baseUrl || undefined,
      health_endpoint: normalized.healthEndpoint,
      root_path: normalized.rootPath || undefined,
      category,
      summitflow_hosted: summitflowHosted || undefined,
      agent_hub_permission: syncAgentHubPermission
        ? {
            permission_tier: permissionTier,
            auto_exec_enabled: autoExecEnabled,
            execution_start_hour: EXECUTION_START_HOUR,
            execution_end_hour: EXECUTION_END_HOUR,
          }
        : undefined,
      onboarding: normalized.rootPath ? { ...DEFAULT_ONBOARDING } : undefined,
    })
  }

  const normalizedRootPath = normalizeRootPath(rootPath)
  const healthPreview = buildHealthPreview(baseUrl, healthEndpoint)

  return {
    fields: { name, projectId, baseUrl, healthEndpoint, rootPath, category },
    agentHub: { syncAgentHubPermission, permissionTier, autoExecEnabled },
    errors,
    isPending: mutation.isPending,
    preview: { normalizedRootPath, healthPreview },
    handlers: {
      handleNameChange,
      handleProjectIdChange,
      handleBaseUrlChange,
      handleHealthEndpointChange,
      handleRootPathChange,
      handleCategoryChange,
      handleSubmit,
      setSyncAgentHubPermission,
      setPermissionTier,
      setAutoExecEnabled,
    },
  }
}
