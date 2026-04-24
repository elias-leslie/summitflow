export const AMBIGUOUS_DISPATCH_PATTERN =
  /(fetch failed|failed to fetch|network|socket hang up|econnreset)/i

export function isAmbiguousDispatchError(message: string): boolean {
  return AMBIGUOUS_DISPATCH_PATTERN.test(message)
}
