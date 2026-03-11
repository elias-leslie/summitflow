interface SearchParamsLike {
  toString(): string
}

export function buildUrlWithUpdatedSearchParams(
  pathname: string,
  searchParams: SearchParamsLike,
  params: Record<string, string | null>,
): string {
  const nextParams = new URLSearchParams(searchParams.toString())

  for (const [key, value] of Object.entries(params)) {
    if (value === null) {
      nextParams.delete(key)
      continue
    }

    nextParams.set(key, value)
  }

  const query = nextParams.toString()
  return `${pathname}${query ? `?${query}` : ''}`
}
