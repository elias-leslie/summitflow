/**
 * Shared API utilities - DRY helpers for common fetch patterns.
 */

import { getApiBaseUrl } from '../api-config'

/**
 * Build query string from optional params object.
 * Skips undefined/null values.
 */
export function buildQueryString(
  params: Record<string, string | number | boolean | undefined | null>,
): string {
  const searchParams = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      searchParams.append(key, String(value))
    }
  }
  const str = searchParams.toString()
  return str ? `?${str}` : ''
}

/**
 * Get API base URL for backend calls.
 * Delegates to api-config.ts for proper hostname detection.
 */
export function getApiBase(): string {
  return getApiBaseUrl()
}

/**
 * Standard error response handler.
 * Throws with error.detail if available, otherwise generic message.
 */
export async function throwFromResponse(
  res: Response,
  defaultMessage: string,
): Promise<never> {
  let detail: string | undefined
  try {
    const error = await res.json()
    detail = error.detail
  } catch {
    // JSON parse failed — fall through to default
  }
  throw new Error(detail || defaultMessage)
}

/**
 * Fetch with standard error handling.
 * Handles both simple errors and JSON detail errors.
 */
export async function fetchWithErrorHandling<T>(
  url: string,
  options: RequestInit & { errorMessage?: string } = {},
): Promise<T> {
  const { errorMessage = 'Request failed', ...fetchOptions } = options
  const res = await fetch(url, fetchOptions)
  if (!res.ok) {
    await throwFromResponse(res, errorMessage)
  }
  return res.json()
}

