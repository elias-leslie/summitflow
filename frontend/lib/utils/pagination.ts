/**
 * Generate page numbers for pagination with ellipsis for large page counts.
 *
 * @param currentPage - Current active page (1-indexed)
 * @param totalPages - Total number of pages
 * @returns Array of page numbers or 'ellipsis' markers
 */
export function generatePageNumbers(
  currentPage: number,
  totalPages: number,
): (number | 'ellipsis')[] {
  const pages: (number | 'ellipsis')[] = []

  if (totalPages <= 7) {
    // Show all pages if 7 or fewer
    for (let i = 1; i <= totalPages; i++) pages.push(i)
  } else {
    // Always show first page
    pages.push(1)

    if (currentPage > 3) {
      pages.push('ellipsis')
    }

    // Show pages around current
    const start = Math.max(2, currentPage - 1)
    const end = Math.min(totalPages - 1, currentPage + 1)

    for (let i = start; i <= end; i++) {
      pages.push(i)
    }

    if (currentPage < totalPages - 2) {
      pages.push('ellipsis')
    }

    // Always show last page
    pages.push(totalPages)
  }

  return pages
}

export const DEFAULT_ITEMS_PER_PAGE = 10

/**
 * Calculate pagination info
 */
export function getPaginationInfo(
  currentPage: number,
  totalItems: number,
  itemsPerPage = DEFAULT_ITEMS_PER_PAGE,
) {
  const totalPages = Math.ceil(totalItems / itemsPerPage)
  const startItem = (currentPage - 1) * itemsPerPage + 1
  const endItem = Math.min(currentPage * itemsPerPage, totalItems)

  return { totalPages, startItem, endItem }
}
