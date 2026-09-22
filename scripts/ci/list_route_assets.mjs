#!/usr/bin/env node
// Report the Vite manifest's static and dynamic asset closures separately.
// Static imports are required to render the selected route. Dynamic imports
// remain delayed and must never be counted toward its initial-load budget.

import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const ROUTES = {
  '/login': { views: ['src/views/LoginPage.vue'], chunkNames: ['auth-pages'] },
  '/dashboard': {
    views: ['src/components/common/AppLayout.vue', 'src/views/DashboardPage.vue'],
  },
  '/ai-chat': {
    views: ['src/components/common/AppLayout.vue', 'src/views/AIChatPage.vue'],
  },
  '/backtests': {
    views: ['src/components/common/AppLayout.vue', 'src/views/BacktestPage.vue'],
  },
  '/backtest-detail': {
    views: ['src/components/common/AppLayout.vue', 'src/views/BacktestResultPage.vue'],
  },
  '/knowledge-base': {
    views: ['src/components/common/AppLayout.vue', 'src/views/KnowledgeBasePage.vue'],
  },
  '/strategies': {
    views: ['src/components/common/AppLayout.vue', 'src/views/StrategyPage.vue'],
  },
  '/workspace-detail': {
    views: ['src/components/common/AppLayout.vue', 'src/views/workspace/WorkspaceDetailPage.vue'],
  },
}

const SUPPORTED_KINDS = new Set([
  'entry-file',
  'entry-initial-js',
  'initial-js',
  'delayed-js',
  'initial',
  'delayed',
])

function parseArgs(argv) {
  const positional = []
  let kind = 'initial-js'
  let format = 'lines'

  for (const arg of argv.slice(2)) {
    if (arg.startsWith('--kind=')) {
      kind = arg.slice('--kind='.length)
    } else if (arg.startsWith('--format=')) {
      format = arg.slice('--format='.length)
    } else if (arg.startsWith('--')) {
      throw new Error(`unsupported option: ${arg}`)
    } else {
      positional.push(arg)
    }
  }

  if (positional.length !== 2) {
    throw new Error('Usage: list_route_assets.mjs <route> <dist_dir> [--kind=...] [--format=json]')
  }
  if (!SUPPORTED_KINDS.has(kind)) {
    throw new Error(`unsupported kind "${kind}"; expected one of ${[...SUPPORTED_KINDS].join(', ')}`)
  }
  if (format !== 'lines' && format !== 'json') {
    throw new Error(`unsupported format "${format}"; expected lines or json`)
  }

  return { route: positional[0], distDir: positional[1], kind, format }
}

function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function validateManifest(manifest) {
  if (!isRecord(manifest) || Object.keys(manifest).length === 0) {
    throw new Error('manifest must be a non-empty object')
  }

  const entries = Object.entries(manifest)
  for (const [source, entry] of entries) {
    if (!source || !isRecord(entry)) {
      throw new Error(`manifest entry "${source}" must be an object`)
    }
    if (typeof entry.file !== 'string' || entry.file.length === 0) {
      throw new Error(`manifest entry "${source}" is missing file`)
    }
    for (const field of ['imports', 'dynamicImports', 'css', 'assets']) {
      if (entry[field] !== undefined && (!Array.isArray(entry[field]) || entry[field].some(item => typeof item !== 'string'))) {
        throw new Error(`manifest entry "${source}" has invalid ${field}`)
      }
    }
  }

  const entrySources = entries.filter(([, entry]) => entry.isEntry === true).map(([source]) => source)
  if (entrySources.length !== 1) {
    throw new Error(`expected exactly one Vite entry, found ${entrySources.length}`)
  }

  for (const [source, entry] of entries) {
    for (const field of ['imports', 'dynamicImports']) {
      for (const dependency of entry[field] || []) {
        if (!Object.hasOwn(manifest, dependency)) {
          throw new Error(`manifest entry "${source}" references missing ${field} entry "${dependency}"`)
        }
      }
    }
  }

  return { entrySource: entrySources[0] }
}

function validateAssetPath(assetPath) {
  if (path.posix.isAbsolute(assetPath) || assetPath.includes('\\')) {
    throw new Error(`unsafe manifest asset path "${assetPath}"`)
  }
  const segments = assetPath.split('/')
  if (segments.some(segment => segment === '' || segment === '.' || segment === '..')) {
    throw new Error(`unsafe manifest asset path "${assetPath}"`)
  }
  return assetPath
}

function collectStaticClosure(manifest, rootSource) {
  const sourceKeys = new Set()
  const files = new Set()

  function visit(source) {
    if (sourceKeys.has(source)) return
    sourceKeys.add(source)
    const entry = manifest[source]
    files.add(validateAssetPath(entry.file))
    for (const asset of [...(entry.css || []), ...(entry.assets || [])]) {
      files.add(validateAssetPath(asset))
    }
    for (const dependency of entry.imports || []) visit(dependency)
  }

  visit(rootSource)
  return { sourceKeys, files }
}

function collectReachableSources(manifest, rootSource) {
  const reachable = new Set()

  function visit(source) {
    if (reachable.has(source)) return
    reachable.add(source)
    const entry = manifest[source]
    for (const dependency of [...(entry.imports || []), ...(entry.dynamicImports || [])]) {
      visit(dependency)
    }
  }

  visit(rootSource)
  return reachable
}

function analyzeManifest(manifest, route) {
  const { entrySource } = validateManifest(manifest)
  const routeDefinition = ROUTES[route]
  if (!routeDefinition) {
    throw new Error(`unsupported route "${route}"; known routes: ${Object.keys(ROUTES).join(', ')}`)
  }

  const reachableSources = collectReachableSources(manifest, entrySource)
  const missingViews = routeDefinition.views.filter(source => !Object.hasOwn(manifest, source))
  const resolvedRouteSources = routeDefinition.views.filter(source => Object.hasOwn(manifest, source))
  if (missingViews.length > 0) {
    const routeChunks = Object.entries(manifest)
      .filter(([, entry]) => routeDefinition.chunkNames?.includes(entry.name) && entry.isDynamicEntry === true)
      .map(([source]) => source)
    if (routeChunks.length !== 1) {
      throw new Error(`route "${route}" references missing manifest source "${missingViews[0]}"`)
    }
    resolvedRouteSources.push(routeChunks[0])
  }

  const unreachableRouteSources = resolvedRouteSources.filter(source => !reachableSources.has(source))
  if (unreachableRouteSources.length > 0) {
    throw new Error(
      `route "${route}" references manifest source(s) not reachable from entry: ${unreachableRouteSources.join(', ')}`,
    )
  }

  const entryClosure = collectStaticClosure(manifest, entrySource)
  const routeClosures = resolvedRouteSources.map(source => collectStaticClosure(manifest, source))
  const initialSourceKeys = new Set(entryClosure.sourceKeys)
  const initialFiles = new Set(entryClosure.files)
  const routeInitialFiles = new Set()

  for (const closure of routeClosures) {
    for (const source of closure.sourceKeys) initialSourceKeys.add(source)
    for (const file of closure.files) {
      initialFiles.add(file)
      routeInitialFiles.add(file)
    }
  }

  const delayedFiles = new Set()
  const visitedDynamicSources = new Set()

  function visitDynamicImports(source) {
    if (visitedDynamicSources.has(source)) return
    visitedDynamicSources.add(source)
    const entry = manifest[source]
    for (const dependency of entry.dynamicImports || []) {
      const closure = collectStaticClosure(manifest, dependency)
      for (const dependencySource of closure.sourceKeys) {
        visitDynamicImports(dependencySource)
      }
      for (const file of closure.files) delayedFiles.add(file)
    }
  }

  for (const source of initialSourceKeys) visitDynamicImports(source)

  const initialJsFiles = [...initialFiles].filter(isJavaScriptAsset).sort()
  const delayedJsFiles = [...delayedFiles]
    .filter(file => !initialFiles.has(file) && isJavaScriptAsset(file))
    .sort()

  return {
    route,
    entrySource,
    entryFile: validateAssetPath(manifest[entrySource].file),
    routeSources: resolvedRouteSources,
    entryInitialFiles: [...entryClosure.files].sort(),
    routeInitialFiles: [...routeInitialFiles].sort(),
    initialFiles: [...initialFiles].sort(),
    delayedFiles: [...delayedFiles].filter(file => !initialFiles.has(file)).sort(),
    entryInitialJsFiles: [...entryClosure.files].filter(isJavaScriptAsset).sort(),
    initialJsFiles,
    delayedJsFiles,
  }
}

function isJavaScriptAsset(filename) {
  return /\.(?:c|m)?js$/i.test(filename)
}

function isWithinDirectory(rootPath, candidatePath) {
  const relativePath = path.relative(rootPath, candidatePath)
  return relativePath === '' || (!path.isAbsolute(relativePath) && relativePath !== '..' && !relativePath.startsWith(`..${path.sep}`))
}

function loadReport(route, distDir) {
  const root = path.resolve(distDir)
  const realRoot = fs.realpathSync(root)
  if (!fs.statSync(realRoot).isDirectory()) {
    throw new Error(`dist directory is not a directory: ${root}`)
  }

  const manifestPath = path.join(root, '.vite', 'manifest.json')
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`required Vite manifest is missing: ${manifestPath}`)
  }

  const realManifestPath = fs.realpathSync(manifestPath)
  if (!isWithinDirectory(realRoot, realManifestPath)) {
    throw new Error(`Vite manifest escapes dist directory: ${manifestPath}`)
  }

  let manifest
  try {
    manifest = JSON.parse(fs.readFileSync(realManifestPath, 'utf8'))
  } catch (error) {
    throw new Error(`failed to parse Vite manifest ${manifestPath}: ${error.message}`)
  }

  const report = analyzeManifest(manifest, route)
  for (const file of new Set([...report.entryInitialFiles, ...report.routeInitialFiles, ...report.delayedFiles])) {
    const absolutePath = path.resolve(root, file)
    if (!isWithinDirectory(root, absolutePath)) {
      throw new Error(`manifest asset escapes dist directory: ${file}`)
    }
    if (!fs.existsSync(absolutePath)) {
      throw new Error(`manifest asset is missing: ${file}`)
    }

    let realAssetPath
    try {
      realAssetPath = fs.realpathSync(absolutePath)
    } catch {
      throw new Error(`manifest asset is missing: ${file}`)
    }
    if (!isWithinDirectory(realRoot, realAssetPath)) {
      throw new Error(`manifest asset escapes dist directory: ${file}`)
    }
    if (!fs.statSync(realAssetPath).isFile()) throw new Error(`manifest asset is missing: ${file}`)
  }
  return report
}

function filesForKind(report, kind) {
  switch (kind) {
    case 'entry-file':
      return [report.entryFile]
    case 'entry-initial-js':
      return report.entryInitialFiles.filter(isJavaScriptAsset)
    case 'initial-js':
      return report.initialJsFiles
    case 'delayed-js':
      return report.delayedJsFiles
    case 'initial':
      return report.initialFiles
    case 'delayed':
      return report.delayedFiles
  }
}

function main(argv) {
  try {
    const { route, distDir, kind, format } = parseArgs(argv)
    const report = loadReport(route, distDir)
    if (format === 'json') {
      process.stdout.write(`${JSON.stringify(report, null, 2)}\n`)
      return
    }
    for (const file of filesForKind(report, kind)) process.stdout.write(`${file}\n`)
  } catch (error) {
    console.error(`ERROR: ${error.message}`)
    process.exitCode = 1
  }
}

const invokedPath = process.argv[1]
if (invokedPath && pathToFileURL(path.resolve(invokedPath)).href === import.meta.url) {
  main(process.argv)
}

export { analyzeManifest, loadReport, ROUTES }
