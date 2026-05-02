export type SortDirection = 'asc' | 'desc'

export function nextSortState<Field extends string>(
  currentField: Field,
  currentDir: SortDirection,
  field: Field,
): { field: Field; dir: SortDirection } {
  return currentField === field
    ? { field, dir: currentDir === 'asc' ? 'desc' : 'asc' }
    : { field, dir: 'asc' as const }
}

export function toggleSetValue<Value>(values: Set<Value>, value: Value) {
  const next = new Set(values)
  if (next.has(value)) {
    next.delete(value)
  } else {
    next.add(value)
  }
  return next
}
