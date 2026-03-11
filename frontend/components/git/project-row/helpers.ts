import type { CommitInfo } from '@/lib/api/git-enhanced'

export function isAgentCommit(commit: CommitInfo): boolean {
  return commit.author_email.includes('anthropic.com')
}
