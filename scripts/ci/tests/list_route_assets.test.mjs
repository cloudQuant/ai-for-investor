import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { afterEach, describe, it } from 'node:test'
import { loadReport } from '../list_route_assets.mjs'

const helperPath = new URL('../list_route_assets.mjs', import.meta.url)
const temporaryRoots = []
const temporaryLinks = []

function removeTemporaryLink(linkPath) {
  try {
    fs.unlinkSync(linkPath)
  } catch (error) {
    if (error.code === 'ENOENT') return
    if (!['EISDIR', 'EPERM', 'EINVAL'].includes(error.code)) throw error
    fs.rmSync(linkPath, { recursive: true, force: true })
  }
}

function makeDist(manifestText) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'route-assets-'))
  temporaryRoots.push(root)
  fs.mkdirSync(path.join(root, '.vite'), { recursive: true })
  fs.writeFileSync(path.join(root, '.vite', 'manifest.json'), manifestText)
  return root
}

function makeManifestDist(manifest) {
  const root = makeDist(JSON.stringify(manifest))
  for (const entry of Object.values(manifest)) {
    for (const file of [entry.file, ...(entry.css || []), ...(entry.assets || [])]) {
      const absolutePath = path.join(root, file)
      fs.mkdirSync(path.dirname(absolutePath), { recursive: true })
      fs.writeFileSync(absolutePath, file)
    }
  }
  return root
}

const validManifest = {
  'src/main.ts': {
    file: 'assets/index.js',
    isEntry: true,
    imports: ['_shared.js'],
    dynamicImports: ['src/views/LoginPage.vue', 'src/views/StrategyPage.vue'],
  },
  '_shared.js': {
    file: 'assets/application-vendor.js',
    imports: ['src/main.ts'],
  },
  'src/views/LoginPage.vue': {
    file: 'assets/login.js',
    imports: ['_login.js'],
    dynamicImports: ['src/components/common/MonacoEditor.vue'],
  },
  '_login.js': {
    file: 'assets/login-shared.js',
    css: ['assets/login.css'],
  },
  'src/views/StrategyPage.vue': {
    file: 'assets/strategy.js',
  },
  'src/components/common/MonacoEditor.vue': {
    file: 'assets/monaco-wrapper.js',
    imports: ['_monaco-core.js'],
    dynamicImports: ['_monaco-worker.js'],
  },
  '_monaco-core.js': {
    file: 'assets/monaco-core.js',
  },
  '_monaco-worker.js': {
    file: 'assets/monaco-worker.js',
  },
}

afterEach(() => {
  for (const link of temporaryLinks.splice(0)) removeTemporaryLink(link)
  for (const root of temporaryRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

function createSymlinkOrSkip(testContext, targetPath, linkPath, type) {
  try {
    fs.symlinkSync(targetPath, linkPath, type)
    temporaryLinks.push(linkPath)
    return true
  } catch (error) {
    const unsupported = ['ENOTSUP', 'EOPNOTSUPP'].includes(error.code)
      || (process.platform === 'win32' && ['EPERM', 'EACCES'].includes(error.code))
    if (!unsupported) throw error
    testContext.skip(`symbolic links are unavailable: ${error.code}`)
    return false
  }
}

describe('list_route_assets manifest handling', () => {
  it('reports static first-load and dynamic delayed closures separately', () => {
    const dist = makeManifestDist(validManifest)
    const report = loadReport('/login', dist)

    assert.deepEqual(report.initialFiles, [
      'assets/application-vendor.js',
      'assets/index.js',
      'assets/login-shared.js',
      'assets/login.css',
      'assets/login.js',
    ])
    assert.deepEqual(report.initialJsFiles, [
      'assets/application-vendor.js',
      'assets/index.js',
      'assets/login-shared.js',
      'assets/login.js',
    ])
    assert.deepEqual(report.entryInitialJsFiles, ['assets/application-vendor.js', 'assets/index.js'])
    assert.ok(!report.initialFiles.includes('assets/monaco-core.js'))
    assert.ok(report.delayedFiles.includes('assets/monaco-wrapper.js'))
    assert.ok(report.delayedFiles.includes('assets/monaco-core.js'))
    assert.ok(report.delayedFiles.includes('assets/monaco-worker.js'))
    assert.ok(report.delayedFiles.includes('assets/strategy.js'))
    assert.ok(!report.delayedFiles.includes('assets/login.js'))
  })

  it('fails closed when the manifest is missing or malformed', () => {
    const missing = fs.mkdtempSync(path.join(os.tmpdir(), 'route-assets-missing-'))
    temporaryRoots.push(missing)
    assert.throws(() => loadReport('/login', missing), /required Vite manifest is missing/)

    const malformed = makeDist('{')
    assert.throws(() => loadReport('/login', malformed), /failed to parse Vite manifest/)

    const invalidSchema = makeDist(JSON.stringify({
      'src/main.ts': { file: 'assets/index.js', isEntry: true, imports: '_shared.js' },
    }))
    assert.throws(() => loadReport('/login', invalidSchema), /has invalid imports/)
  })

  it('fails closed when the requested route cannot be resolved from the manifest', () => {
    const dist = makeManifestDist({ 'src/main.ts': { file: 'assets/index.js', isEntry: true } })
    assert.throws(() => loadReport('/login', dist), /route "\/login" references missing manifest source/)
    assert.throws(() => loadReport('/unknown', dist), /unsupported route "\/unknown"/)

    const disconnected = makeManifestDist({
      'src/main.ts': {
        file: 'assets/index.js',
        isEntry: true,
        dynamicImports: ['src/views/StrategyPage.vue'],
      },
      'src/views/LoginPage.vue': { file: 'assets/login.js' },
      'src/views/StrategyPage.vue': { file: 'assets/strategy.js' },
    })
    assert.throws(() => loadReport('/login', disconnected), /not reachable from entry/)
  })

  it('resolves an explicitly named Vite route chunk when manual chunking hides the source key', () => {
    const dist = makeManifestDist({
      'src/main.ts': {
        file: 'assets/index.js',
        isEntry: true,
        dynamicImports: ['_auth-pages.js'],
      },
      '_auth-pages.js': {
        file: 'assets/auth-pages.js',
        name: 'auth-pages',
        isDynamicEntry: true,
      },
    })

    const report = loadReport('/login', dist)
    assert.deepEqual(report.routeSources, ['_auth-pages.js'])
    assert.ok(report.initialJsFiles.includes('assets/auth-pages.js'))
  })

  it('fails closed in the CLI when a manifest dependency points nowhere', () => {
    const dist = makeManifestDist({
      'src/main.ts': {
        file: 'assets/index.js',
        isEntry: true,
        dynamicImports: ['src/views/LoginPage.vue'],
      },
      'src/views/LoginPage.vue': { file: 'assets/login.js', imports: ['_missing.js'] },
    })
    const result = spawnSync(process.execPath, [helperPath.pathname, '/login', dist], { encoding: 'utf8' })
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /references missing imports entry/)
  })

  it('rejects an asset symlink that resolves outside the dist root', (testContext) => {
    const dist = makeManifestDist({
      'src/main.ts': {
        file: 'assets/index.js',
        isEntry: true,
        dynamicImports: ['src/views/LoginPage.vue'],
      },
      'src/views/LoginPage.vue': { file: 'assets/escaped.js' },
    })
    const outsideRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'route-assets-outside-'))
    temporaryRoots.push(outsideRoot)
    const outsideAsset = path.join(outsideRoot, 'escaped.js')
    fs.writeFileSync(outsideAsset, 'outside')
    const assetLink = path.join(dist, 'assets', 'escaped.js')
    fs.unlinkSync(assetLink)

    const symlinkType = process.platform === 'win32' ? 'file' : undefined
    if (!createSymlinkOrSkip(testContext, outsideAsset, assetLink, symlinkType)) return

    assert.throws(() => loadReport('/login', dist), /manifest asset escapes dist directory: assets\/escaped\.js/)
  })

  it('uses the real dist root when the requested directory is a symlink', (testContext) => {
    const dist = makeManifestDist({
      'src/main.ts': {
        file: 'assets/index.js',
        isEntry: true,
        dynamicImports: ['src/views/LoginPage.vue'],
      },
      'src/views/LoginPage.vue': { file: 'assets/login.js' },
    })
    const parent = fs.mkdtempSync(path.join(os.tmpdir(), 'route-assets-root-link-'))
    temporaryRoots.push(parent)
    const rootLink = path.join(parent, 'dist')
    const symlinkType = process.platform === 'win32' ? 'junction' : undefined
    if (!createSymlinkOrSkip(testContext, dist, rootLink, symlinkType)) return

    const report = loadReport('/login', rootLink)
    assert.deepEqual(report.initialJsFiles, ['assets/index.js', 'assets/login.js'])
  })
})
