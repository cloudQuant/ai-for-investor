import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, describe, it } from 'node:test'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const compareScript = path.join(repoRoot, 'scripts/ci/compare_bundle_size.sh')
const temporaryRoots = []

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

function makeDist({ entryName = 'index-entry.js', entryContent, decoyFirst = true }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-ratchet-'))
  temporaryRoots.push(root)
  fs.mkdirSync(path.join(root, '.vite'), { recursive: true })
  fs.mkdirSync(path.join(root, 'assets'), { recursive: true })
  const manifest = {
    'src/main.ts': {
      file: `assets/${entryName}`,
      isEntry: true,
      dynamicImports: ['src/views/LoginPage.vue'],
    },
    'src/views/LoginPage.vue': { file: 'assets/login.js' },
  }
  fs.writeFileSync(path.join(root, '.vite/manifest.json'), JSON.stringify(manifest))

  const entryPath = path.join(root, 'assets', entryName)
  const decoyPath = path.join(root, 'assets/index-decoy.js')
  const writeEntry = () => fs.writeFileSync(entryPath, entryContent)
  const writeDecoy = () => fs.writeFileSync(decoyPath, `${'decoy-entry-content;'.repeat(2000)}`)
  if (decoyFirst) {
    writeDecoy()
    writeEntry()
  } else {
    writeEntry()
    writeDecoy()
  }
  fs.writeFileSync(path.join(root, 'assets/login.js'), 'login view')
  return { root, entryPath, decoyPath }
}

function gzip(pathname) {
  const result = spawnSync('gzip', ['-n', '-c', '-9', pathname])
  assert.equal(result.status, 0, result.stderr.toString())
  return result.stdout
}

function compare(dist, baseBytes, env = {}) {
  return spawnSync('bash', [compareScript, dist, String(baseBytes)], {
    cwd: repoRoot,
    encoding: 'utf8',
    env: { ...process.env, GITHUB_STEP_SUMMARY: '', ...env },
  })
}

function deterministicRandomBytes(length) {
  let state = 123456789
  const bytes = Buffer.alloc(length)
  for (let index = 0; index < length; index += 1) {
    state ^= state << 13
    state ^= state >>> 17
    state ^= state << 5
    bytes[index] = state & 0xff
  }
  return bytes
}

describe('bundle-size entry comparison', () => {
  it('uses the manifest entry when multiple index chunks appear in either filesystem order', () => {
    const content = 'the real entry'.repeat(30)
    const first = makeDist({ entryContent: content, decoyFirst: true })
    const second = makeDist({ entryContent: content, decoyFirst: false })
    const expectedBytes = gzip(first.entryPath).length

    assert.notEqual(expectedBytes, gzip(first.decoyPath).length)
    for (const dist of [first, second]) {
      const result = compare(dist.root, expectedBytes)
      assert.equal(result.status, 0, result.stderr || result.stdout)
      assert.match(result.stdout, new RegExp(`Current entry gzip: ${expectedBytes} bytes`))
      assert.match(result.stdout, /within ratchet/)
    }
  })

  it('produces identical gzip bytes for identical content with different names and mtimes', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-gzip-metadata-'))
    temporaryRoots.push(root)
    const first = path.join(root, 'first-name.js')
    const second = path.join(root, 'different-name.js')
    const content = deterministicRandomBytes(2048)
    fs.writeFileSync(first, content)
    fs.writeFileSync(second, content)
    fs.utimesSync(first, new Date('2020-01-01T00:00:00Z'), new Date('2020-01-01T00:00:00Z'))
    fs.utimesSync(second, new Date('2026-10-13T00:00:00Z'), new Date('2026-10-13T00:00:00Z'))

    assert.deepEqual(gzip(first), gzip(second))
  })

  it('accepts exactly 10.0% growth and rejects a 10.x% regression', () => {
    const dist = makeDist({ entryContent: '' })
    let currentBytes = 0
    for (let rawLength = 16384; rawLength < 16512; rawLength += 1) {
      fs.writeFileSync(dist.entryPath, deterministicRandomBytes(rawLength))
      currentBytes = gzip(dist.entryPath).length
      if (currentBytes % 11 === 0) break
    }
    assert.equal(currentBytes % 11, 0, 'fixture should permit an exact 10% boundary')

    const exactTenPercentBase = (currentBytes / 11) * 10
    const exactBoundary = compare(dist.root, exactTenPercentBase)
    assert.equal(exactBoundary.status, 0, exactBoundary.stderr || exactBoundary.stdout)
    assert.match(exactBoundary.stdout, /within ratchet/)

    const overTenPercentBase = Math.floor((currentBytes * 1000) / 1101)
    assert.ok(currentBytes * 100 > overTenPercentBase * 110)
    assert.ok(currentBytes * 100 < overTenPercentBase * 111)
    const overBoundary = compare(dist.root, overTenPercentBase)
    assert.equal(overBoundary.status, 1, overBoundary.stdout)
    assert.match(overBoundary.stdout, /::error::Bundle size growth .* exceeds 10% threshold/)
  })

  it('keeps the explicit override and missing-baseline behavior', () => {
    const dist = makeDist({ entryContent: 'large current entry'.repeat(200) })
    for (const env of [
      { PR_LABELS: 'BUNDLE_SIZE_GROWTH_OVERRIDE' },
      { PR_BODY: '<!-- bundle-size-override: intentional fixture -->' },
    ]) {
      const overridden = compare(dist.root, 1, env)
      assert.equal(overridden.status, 0, overridden.stderr || overridden.stdout)
      assert.match(overridden.stdout, /override active/)
    }

    const missing = compare(dist.root, '')
    assert.equal(missing.status, 0, missing.stderr || missing.stdout)
    assert.match(missing.stdout, /::notice::bundle-size base missing, ratchet skipped/)
  })
})
