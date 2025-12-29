import { fetchWithErrorHandling } from "./utils";

// =============================================================================
// Extraction Prompts Types
// =============================================================================

export type ExtractionPromptType =
  | "feature_extraction"
  | "vision_extraction"
  | "goals_extraction";

export interface ExtractionPrompt {
  prompt_type: ExtractionPromptType;
  prompt_text: string;
  primary_agent: "claude" | "gemini";
  primary_model: string;
  is_default: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ExtractionPromptUpdate {
  prompt_text: string;
  primary_agent?: "claude" | "gemini";
  primary_model?: string;
}

export interface ExtractionPromptsExport {
  project_id: string;
  exported_at: string;
  prompts: ExtractionPrompt[];
}

// =============================================================================
// Extraction Prompts API
// =============================================================================

export async function getExtractionPrompts(
  projectId: string
): Promise<ExtractionPrompt[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/extraction-prompts`,
    { errorMessage: "Failed to fetch extraction prompts" }
  );
}

export async function getExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType
): Promise<ExtractionPrompt> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`,
    { errorMessage: "Failed to fetch extraction prompt" }
  );
}

export async function updateExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType,
  config: ExtractionPromptUpdate
): Promise<ExtractionPrompt> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt_text: config.prompt_text,
        primary_agent: config.primary_agent ?? "claude",
        primary_model: config.primary_model ?? "claude-sonnet-4-5",
      }),
      errorMessage: "Failed to update extraction prompt",
    }
  );
}

export async function deleteExtractionPrompt(
  projectId: string,
  promptType: ExtractionPromptType
): Promise<{ deleted: boolean; reverted_to_default: boolean; prompt_type: string }> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/extraction-prompts/${promptType}`,
    { method: "DELETE", errorMessage: "Failed to delete extraction prompt" }
  );
}

export async function exportExtractionPrompts(
  projectId: string,
  format: "json" = "json"
): Promise<ExtractionPromptsExport> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/roundtable/extraction-prompts/export?format=${format}`,
    { errorMessage: "Failed to export extraction prompts" }
  );
}
