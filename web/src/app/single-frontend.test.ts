// @vitest-environment node
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('single frontend boundary', () => {
  it('has one HTML entry and no standalone experience build or runtime', () => {
    const root = process.cwd()
    expect(readdirSync(root).filter((file) => file.endsWith('.html'))).toEqual(['index.html'])
    expect(existsSync(resolve(root, 'vite.experience.config.ts'))).toBe(false)
    expect(existsSync(resolve(root, 'src/experience/main.tsx'))).toBe(false)
    expect(readFileSync(resolve(root, 'index.html'), 'utf8')).toContain('/src/main.tsx')
    expect(readFileSync(resolve(root, 'src/app/router.tsx'), 'utf8')).toContain("path: '/experience.html'")
  })
})
