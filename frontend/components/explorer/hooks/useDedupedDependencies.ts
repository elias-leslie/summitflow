/**
 * useDedupedDependencies - Deduplication hook for dependency entries
 *
 * Groups dependency entries by package name, merging source_files into an array.
 * Keeps the highest version if versions differ.
 */

import { useMemo } from 'react'
import type { ExplorerEntry } from '@/lib/api/explorer'

export interface DedupedDependency extends ExplorerEntry {
  // Extended metadata for deduplicated entries
  metadata: ExplorerEntry['metadata'] & {
    source_files: string[]
    version_conflict: boolean
    all_versions: string[]
  }
}

/**
 * Compares two semver-like version strings.
 * Returns positive if a > b, negative if a < b, 0 if equal.
 */
function compareVersions(a: string, b: string): number {
  const partsA = a.replace(/[^0-9.]/g, '').split('.').map(Number)
  const partsB = b.replace(/[^0-9.]/g, '').split('.').map(Number)

  for (let i = 0; i < Math.max(partsA.length, partsB.length); i++) {
    const numA = partsA[i] ?? 0
    const numB = partsB[i] ?? 0
    if (numA !== numB) return numA - numB
  }
  return 0
}

/**
 * Deduplicates dependency entries by package name.
 *
 * @param entries - Raw dependency entries from API
 * @returns Deduplicated entries with merged source_files
 */
export function useDedupedDependencies(
  entries: ExplorerEntry[],
): DedupedDependency[] {
  return useMemo(() => {
    // Group by package name
    const byName = new Map<string, ExplorerEntry[]>()

    for (const entry of entries) {
      const existing = byName.get(entry.name)
      if (existing) {
        existing.push(entry)
      } else {
        byName.set(entry.name, [entry])
      }
    }

    // Merge grouped entries
    const dedupedEntries: DedupedDependency[] = []

    for (const [, group] of byName) {
      if (group.length === 1) {
        // Single entry - just add source_files array
        const entry = group[0]
        const sourceFile = entry.metadata.source_file as string | undefined
        dedupedEntries.push({
          ...entry,
          metadata: {
            ...entry.metadata,
            source_files: sourceFile ? [sourceFile] : [],
            version_conflict: false,
            all_versions: entry.metadata.locked_version
              ? [entry.metadata.locked_version as string]
              : [],
          },
        })
      } else {
        // Multiple entries - merge
        const sourceFiles: string[] = []
        const versions: string[] = []

        for (const entry of group) {
          const sourceFile = entry.metadata.source_file as string | undefined
          if (sourceFile && !sourceFiles.includes(sourceFile)) {
            sourceFiles.push(sourceFile)
          }
          const version = entry.metadata.locked_version as string | undefined
          if (version && !versions.includes(version)) {
            versions.push(version)
          }
        }

        // Find entry with highest version
        let primaryEntry = group[0]
        for (const entry of group) {
          const currentVersion = entry.metadata.locked_version as
            | string
            | undefined
          const primaryVersion = primaryEntry.metadata.locked_version as
            | string
            | undefined
          if (
            currentVersion &&
            primaryVersion &&
            compareVersions(currentVersion, primaryVersion) > 0
          ) {
            primaryEntry = entry
          }
        }

        // Merge vulnerabilities from all entries
        const mergedVulns = {
          critical: 0,
          high: 0,
          medium: 0,
          low: 0,
        }
        for (const entry of group) {
          const vulns = entry.metadata.vulnerabilities as
            | typeof mergedVulns
            | undefined
          if (vulns) {
            mergedVulns.critical = Math.max(
              mergedVulns.critical,
              vulns.critical ?? 0,
            )
            mergedVulns.high = Math.max(mergedVulns.high, vulns.high ?? 0)
            mergedVulns.medium = Math.max(mergedVulns.medium, vulns.medium ?? 0)
            mergedVulns.low = Math.max(mergedVulns.low, vulns.low ?? 0)
          }
        }

        // Use worst health status
        let worstHealth = primaryEntry.healthStatus
        for (const entry of group) {
          if (
            entry.healthStatus === 'error' ||
            (entry.healthStatus === 'warning' && worstHealth !== 'error')
          ) {
            worstHealth = entry.healthStatus
          }
        }

        dedupedEntries.push({
          ...primaryEntry,
          healthStatus: worstHealth,
          metadata: {
            ...primaryEntry.metadata,
            source_files: sourceFiles,
            version_conflict: versions.length > 1,
            all_versions: versions,
            vulnerabilities:
              mergedVulns.critical +
                mergedVulns.high +
                mergedVulns.medium +
                mergedVulns.low >
              0
                ? mergedVulns
                : primaryEntry.metadata.vulnerabilities,
          },
        })
      }
    }

    // Sort alphabetically by name
    return dedupedEntries.sort((a, b) => a.name.localeCompare(b.name))
  }, [entries])
}
