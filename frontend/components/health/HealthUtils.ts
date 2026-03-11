// Utility functions for Health Tab

export function formatFilePath(path: string | null): string {
  if (!path) return 'Unknown file'
  // Show last 2 parts of path
  const parts = path.split('/')
  return parts.slice(-2).join('/')
}
