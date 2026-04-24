/**
 * Shared API utilities - DRY helpers for common fetch patterns.
 */

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

const JSON_HEADERS = { 'Content-Type': 'application/json' } as const

/** POST JSON body. */
export function postJson<T>(
  url: string,
  data: unknown,
  errorMessage: string,
  headers: Record<string, string> = {},
): Promise<T> {
  return fetchWithErrorHandling<T>(url, {
    method: 'POST',
    headers: { ...JSON_HEADERS, ...headers },
    body: JSON.stringify(data),
    errorMessage,
  })
}

/** PATCH JSON body. */
export function patchJson<T>(
  url: string,
  data: unknown,
  errorMessage: string,
): Promise<T> {
  return fetchWithErrorHandling<T>(url, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(data),
    errorMessage,
  })
}

/** PUT JSON body. */
export function putJson<T>(
  url: string,
  data: unknown,
  errorMessage: string,
): Promise<T> {
  return fetchWithErrorHandling<T>(url, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(data),
    errorMessage,
  })
}

/** DELETE with optional JSON body. */
export function deleteJson<T>(
  url: string,
  errorMessage: string,
  data?: unknown,
): Promise<T> {
  const options: RequestInit & { errorMessage: string } = {
    method: 'DELETE',
    errorMessage,
  }
  if (data !== undefined) {
    options.headers = JSON_HEADERS
    options.body = JSON.stringify(data)
  }
  return fetchWithErrorHandling<T>(url, options)
}
