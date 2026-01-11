import { fetchWithErrorHandling } from "./utils";

// =============================================================================
// Global Extraction Settings Types
// =============================================================================

export interface GlobalExtractionSettings {
  enabled: boolean;
  rpm_limit: number;
  current_rpm: number;
  requests_today: number;
}

export interface GlobalExtractionSettingsUpdate {
  enabled?: boolean;
  rpm_limit?: number;
}

// =============================================================================
// Global Extraction Settings API
// =============================================================================

export async function getGlobalExtractionSettings(): Promise<GlobalExtractionSettings> {
  return fetchWithErrorHandling("/api/memory/extraction", {
    errorMessage: "Failed to fetch global extraction settings",
  });
}

export async function updateGlobalExtractionSettings(
  update: GlobalExtractionSettingsUpdate,
): Promise<GlobalExtractionSettings> {
  return fetchWithErrorHandling("/api/memory/extraction", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
    errorMessage: "Failed to update global extraction settings",
  });
}

// =============================================================================
// Global Cleanup Settings Types
// =============================================================================

export interface CleanupPreset {
  level: number;
  label: string;
  min_age_days: number;
  min_relevance: number;
}

export interface CleanupSettings {
  level: number;
  label: string;
  min_age_days: number;
  min_relevance: number;
  presets: CleanupPreset[];
}

export interface CleanupSettingsUpdate {
  level: number;
}

// =============================================================================
// Global Cleanup Settings API
// =============================================================================

export async function getCleanupSettings(): Promise<CleanupSettings> {
  return fetchWithErrorHandling("/api/memory/cleanup", {
    errorMessage: "Failed to fetch cleanup settings",
  });
}

export async function updateCleanupSettings(
  update: CleanupSettingsUpdate,
): Promise<CleanupSettings> {
  return fetchWithErrorHandling("/api/memory/cleanup", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
    errorMessage: "Failed to update cleanup settings",
  });
}
