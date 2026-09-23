import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), path), 'utf8')

describe('local bundled application fonts', () => {
  it('does not fetch fonts or invoke the remote font loader during builds', () => {
    const layout = read('app/layout.tsx')
    expect(layout).not.toContain('next/font/google')
    expect(layout).toContain("import './fonts.css'")
    expect(read('app/fonts.css')).not.toMatch(/https?:\/\//)
  })

  it('retains every existing subset, weight mapping, font byte, and license notice', () => {
    const manifest = JSON.parse(read('public/fonts/manifest.json')) as {
      assets: Array<{
        file: string
        family: string
        weights: string[]
        unicode_range: string
        bytes: number
        sha256: string
      }>
    }
    const faces = [
      ...read('app/fonts.css').matchAll(/@font-face\s*\{([^}]+)\}/g),
    ].map(([face]) =>
      face.replace(/\s+/g, ' ').replace(/\s*([:;{}])\s*/g, '$1'),
    )
    expect(manifest.assets).toHaveLength(11)
    expect(faces).toHaveLength(41)
    for (const asset of manifest.assets) {
      const bytes = readFileSync(
        resolve(process.cwd(), 'public/fonts', asset.file),
      )
      expect(bytes.length).toBe(asset.bytes)
      expect(createHash('sha256').update(bytes).digest('hex')).toBe(
        asset.sha256,
      )
      for (const weight of asset.weights) {
        const face = faces.find(
          (item) =>
            item.includes(asset.file) &&
            item.includes(`font-weight:${weight};`),
        )
        expect(face).toBeDefined()
        expect(face?.replaceAll('"', '')).toContain(
          `font-family:${asset.family};`,
        )
        expect(
          face?.match(/unicode-range:([^;}]+)/)?.[1].replace(/\s/g, ''),
        ).toBe(asset.unicode_range)
      }
    }
    for (const family of ['Outfit', 'Bricolage Grotesque', 'JetBrains Mono']) {
      expect(read('public/fonts/OFL.txt')).toContain(family)
    }
  })

  it('retains layout variables, metric-adjusted fallbacks and three Latin preloads', () => {
    const css = read('app/fonts.css')
    expect(css).toContain('--font-body:')
    expect(css).toContain('--font-display:')
    expect(css).toContain('--font-mono:')
    for (const metric of [
      '100.18%',
      '99.82%',
      '88.21%',
      '105.43%',
      '75.79%',
      '134.59%',
    ]) {
      expect(css).toContain(metric)
    }
    const layout = read('app/layout.tsx')
    expect(layout.match(/rel="preload"/g)).toHaveLength(3)
    expect(layout.match(/crossOrigin="anonymous"/g)).toHaveLength(3)
  })
})
