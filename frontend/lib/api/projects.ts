/**
 * Project API functions
 *
 * Handles project CRUD operations, health checks, and agent configuration.
 */

import { fetchWithErrorHandling } from "./utils";

export interface Project {
  id: string;
  name: string;
  base_url: string;
  health_endpoint: string;
  created_at: string;
  health_status?: string;
  root_path?: string;
}

export interface ProjectStats {
  features: number;
  tasks: number;
  bugs: number;
  blocked: number;
}

export interface ProjectWithStats {
  id: string;
  name: string;
  base_url: string;
  health_endpoint: string;
  root_path?: string;
  logo_url?: string;
  created_at: string;
  health_status?: string;
  stats: ProjectStats;
}

export interface ProjectsWithStatsResponse {
  projects: ProjectWithStats[];
  total: number;
}

export interface ProjectHealth {
  project_id: string;
  healthy: boolean;
  status_code?: number;
  response_time_ms?: number;
  error?: string;
  checked_at: string;
}

export interface ProjectAgentConfig {
  claude_enabled: boolean;
  gemini_enabled: boolean;
  default_agent: string;
  claude_model: string;
  gemini_model: string;
  memory_enabled: boolean;
  observations_enabled: boolean;
  diary_enabled: boolean;
  patterns_enabled: boolean;
  checkpoints_enabled: boolean;
  context_injection_enabled: boolean;
  component_source: string;
  // Extraction throttle
  extraction_enabled: boolean;
  extraction_rpm_limit: number;
}

export interface ProjectAgentConfigUpdate {
  claude_enabled?: boolean;
  gemini_enabled?: boolean;
  default_agent?: string;
  claude_model?: string;
  gemini_model?: string;
  memory_enabled?: boolean;
  observations_enabled?: boolean;
  diary_enabled?: boolean;
  patterns_enabled?: boolean;
  checkpoints_enabled?: boolean;
  context_injection_enabled?: boolean;
  component_source?: string;
  // Extraction throttle
  extraction_enabled?: boolean;
  extraction_rpm_limit?: number;
}

export async function fetchProjects(): Promise<Project[]> {
  return fetchWithErrorHandling("/api/projects", {
    errorMessage: "Failed to fetch projects",
  });
}

export async function fetchProjectsWithStats(): Promise<ProjectsWithStatsResponse> {
  return fetchWithErrorHandling("/api/projects/with-stats", {
    errorMessage: "Failed to fetch projects with stats",
  });
}

export async function fetchProject(id: string): Promise<Project> {
  return fetchWithErrorHandling(`/api/projects/${id}`, {
    errorMessage: "Failed to fetch project",
  });
}

export async function fetchProjectHealth(id: string): Promise<ProjectHealth> {
  return fetchWithErrorHandling(`/api/projects/${id}/health`, {
    errorMessage: "Failed to check project health",
  });
}

export async function getAgentConfig(
  projectId: string
): Promise<ProjectAgentConfig> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/agents`, {
    errorMessage: "Failed to fetch agent config",
  });
}

export async function updateAgentConfig(
  projectId: string,
  config: ProjectAgentConfigUpdate
): Promise<ProjectAgentConfig> {
  const res = await fetch(`/api/projects/${projectId}/agents`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error("Failed to update agent config");
  return res.json();
}

export async function createProject(project: {
  id: string;
  name: string;
  base_url: string;
  health_endpoint?: string;
}): Promise<Project> {
  return fetchWithErrorHandling("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(project),
    errorMessage: "Failed to create project",
  });
}
