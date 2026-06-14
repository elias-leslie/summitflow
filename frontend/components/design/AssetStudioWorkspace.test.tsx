import { describe, expect, it } from 'vitest'
import { nextAssetReviewStatus } from './AssetStudioWorkspace'

describe('nextAssetReviewStatus', () => {
  it('clears the active review status back to generated', () => {
    expect(nextAssetReviewStatus('approved', 'approved')).toBe('generated')
    expect(nextAssetReviewStatus('rejected', 'rejected')).toBe('generated')
    expect(nextAssetReviewStatus('archived', 'archived')).toBe('generated')
  })

  it('sets requested review status when it is not active', () => {
    expect(nextAssetReviewStatus('generated', 'approved')).toBe('approved')
    expect(nextAssetReviewStatus('approved', 'rejected')).toBe('rejected')
  })
})
