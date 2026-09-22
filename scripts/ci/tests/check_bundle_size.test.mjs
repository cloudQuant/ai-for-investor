import assert from 'node:assert/strict'
import { randomBytes } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { afterEach, describe, it } from 'node:test'

const gatePath = new URL('../check_bundle_size.sh', import.meta.url)
const temporaryRoots = []

function makeDist({ vendorBytes = 32, loginBytes = 32, entryBytes = 0, extraEntryChunks = 0 } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-gate-'))
  temporaryRoots.push(root)
  const extraImports = Array.from({ length: extraEntryChunks }, (_, index) => `_entry-${index}.js`)
  const manifest = {
    'src/main.ts': {
      file: 'assets/index.js',
      isEntry: true,
      imports: ['_application-vendor.js', ...extraImports],
      dynamicImports: ['src/views/LoginPage.vue'],
    },
    '_application-vendor.js': { file: 'assets/application-vendor.js' },
    'src/views/LoginPage.vue': { file: 'assets/login.js' },
  }
  for (const source of extraImports) {
    manifest[source] = { file: `assets/${source.replace(/^_/, '')}` }
  }
  fs.mkdirSync(path.join(root, '.vite'), { recursive: true })
  fs.writeFileSync(path.join(root, '.vite', 'manifest.json'), JSON.stringify(manifest))
  fs.mkdirSync(path.join(root, 'assets'), { recursive: true })
  fs.writeFileSync(path.join(root, 'assets/index.js'), entryBytes > 0 ? randomBytes(entryBytes) : 'export{}')
  fs.writeFileSync(path.join(root, 'assets/application-vendor.js'), randomBytes(vendorBytes))
  fs.writeFileSync(path.join(root, 'assets/login.js'), randomBytes(loginBytes))
  for (const source of extraImports) {
    fs.writeFileSync(path.join(root, 'assets', source.replace(/^_/, '')), 'export{}')
  }
  return root
}

function runGate(dist) {
  return spawnSync('bash', [gatePath.pathname, dist], { encoding: 'utf8' })
}

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

describe('check_bundle_size initial closure budgets', () => {
  it('passes when vendor is included and initial assets fit every hard budget', () => {
    const result = runGate(makeDist({ vendorBytes: 500 * 1024, loginBytes: 20 * 1024 }))

    assert.equal(result.status, 0, result.stdout + result.stderr)
    assert.match(result.stdout, /entry static closure gzip-9 bytes[\s\S]*PASS/)
    assert.match(result.stdout, /\/login initial closure gzip-9 bytes[\s\S]*PASS/)
    assert.match(result.stdout, /largest initial JS gzip-9 bytes[\s\S]*PASS/)
    assert.match(result.stdout, /assets\/application-vendor\.js/)
  })

  it('fails the single-file budget for an oversized initial vendor chunk', () => {
    const result = runGate(makeDist({ vendorBytes: 540 * 1024 + 1, loginBytes: 32 }))

    assert.equal(result.status, 1)
    assert.match(result.stdout, /largest initial JS gzip-9 bytes[\s\S]*\[FAIL\]/)
    assert.match(result.stdout, /assets\/application-vendor\.js/)
  })

  it('fails the aggregate route closure when individually safe JS chunks exceed 640 KiB together', () => {
    const result = runGate(makeDist({ vendorBytes: 500 * 1024, loginBytes: 150 * 1024 }))

    assert.equal(result.status, 1)
    assert.match(result.stdout, /entry static closure gzip-9 bytes[\s\S]*PASS/)
    assert.match(result.stdout, /\/login initial closure gzip-9 bytes[\s\S]*\[FAIL\]/)
    assert.match(result.stdout, /largest initial JS gzip-9 bytes[\s\S]*PASS/)
  })

  it('preserves the existing direct entry gzip budget of 300 KB', () => {
    const result = runGate(makeDist({ entryBytes: 300 * 1024 + 1 }))

    assert.equal(result.status, 1)
    assert.match(result.stdout, /entry chunk gzip bytes[\s\S]*\[FAIL\]/)
  })

  it('preserves the existing four initial JavaScript chunk limits', () => {
    const result = runGate(makeDist({ extraEntryChunks: 3 }))

    assert.equal(result.status, 1)
    assert.match(result.stdout, /entry static initial JS chunks \(all\)[\s\S]*\[FAIL\]/)
    assert.match(result.stdout, /\/login initial JS chunks \(all\)[\s\S]*\[FAIL\]/)
  })
})
