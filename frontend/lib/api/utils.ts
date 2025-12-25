/**
 * Shared API utilities - DRY helpers for common fetch patterns.
 */

/**
 * Build query string from optional params object.
 * Skips undefined/null values.
 */
export function buildQueryString(
  params: Record<string, string | number | boolean | undefined | null>
): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value));
    }
  }
  const str = searchParams.toString();
  return str ? `?${str}` : "";
}

/**
 * Fetch with timeout using AbortController.
 * Default timeout: 30 seconds.
 */
export async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeoutMs: number = 30000
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Get API base URL - empty for relative URLs with Next.js rewrite proxy.
 */
export function getApiBase(): string {
  return "";
}

/**
 * Standard error response handler.
 * Throws with error.detail if available, otherwise generic message.
 */
export async function throwFromResponse(
  res: Response,
  defaultMessage: string
): Promise<never> {
  try {
    const error = await res.json();
    throw new Error(error.detail || defaultMessage);
  } catch {
    throw new Error(defaultMessage);
  }
}

/**
 * Fetch with standard error handling.
 * Handles both simple errors and JSON detail errors.
 */
export async function fetchWithErrorHandling<T>(
  url: string,
  options: RequestInit & { errorMessage?: string } = {}
): Promise<T> {
  const { errorMessage = "Request failed", ...fetchOptions } = options;
  const res = await fetch(url, fetchOptions);
  if (!res.ok) {
    await throwFromResponse(res, errorMessage);
  }
  return res.json();
}

/**
 * Fetch JSON with timeout and error handling.
 * Combines timeout + error handling for common API patterns.
 */
export async function fetchJsonWithTimeout<T>(
  url: string,
  options: RequestInit & { errorMessage?: string; timeoutMs?: number } = {}
): Promise<T> {
  const { errorMessage = "Request failed", timeoutMs = 30000, ...fetchOptions } = options;
  const res = await fetchWithTimeout(url, fetchOptions, timeoutMs);
  if (!res.ok) {
    await throwFromResponse(res, errorMessage);
  }
  return res.json();
}
