/**
 * Roundtable-specific API wrappers for DRY code patterns.
 */

import { fetchJsonWithTimeout, getApiBase } from "./utils";

/** Default timeout for generation operations (2 minutes) */
const GENERATION_TIMEOUT_MS = 120000;

/**
 * Fetch with generation timeout (2 min).
 * Used for long-running generation operations like feature/vision/goals/spec extraction.
 */
export async function fetchWithGenerationTimeout<T>(
  url: string,
  body: Record<string, unknown>,
  errorMessage: string
): Promise<T> {
  return fetchJsonWithTimeout<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    timeoutMs: GENERATION_TIMEOUT_MS,
    errorMessage,
  });
}

/**
 * Execute a roundtable session action (POST to session endpoint).
 * Used for save/accept operations on roundtable sessions.
 */
export async function roundtableSessionAction<T>(
  projectId: string,
  sessionId: string,
  action: string,
  body: Record<string, unknown>,
  errorMessage: string
): Promise<T> {
  const url = `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/${action}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(errorMessage);
  return res.json();
}

/**
 * Build roundtable session URL for generation endpoints.
 */
export function buildRoundtableGenerationUrl(
  projectId: string,
  sessionId: string,
  endpoint: string
): string {
  return `${getApiBase()}/api/projects/${projectId}/roundtable/sessions/${sessionId}/${endpoint}`;
}
