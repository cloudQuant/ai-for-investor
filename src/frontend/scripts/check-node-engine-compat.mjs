import { readFileSync } from 'node:fs'
import process from 'node:process'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import semver from 'semver'

export function inspectNodeEngineCompatibility(manifest, lockfile, runtimeVersion = process.version) {
  const report = { checkedPackages: 0, skippedOptionalPackages: 0, issues: [] }
  const projectRange = manifest?.engines?.node

  if (typeof projectRange !== 'string') {
    report.issues.push({ message: 'package.json must declare engines.node' })
    return report
  }

  try {
    new semver.Range(projectRange)
  } catch (error) {
    report.issues.push({ message: `package.json has an invalid engines.node range: ${error.message}` })
    return report
  }

  if (!semver.satisfies(runtimeVersion, projectRange)) {
    report.issues.push({
      message: `running Node ${runtimeVersion} is outside engines.node ${projectRange}`,
    })
  }

  const lockedPackages = lockfile?.packages
  if (!lockedPackages || typeof lockedPackages !== 'object' || Array.isArray(lockedPackages)) {
    report.issues.push({ message: 'package-lock.json must contain a packages object' })
    return report
  }

  if (lockedPackages['']?.engines?.node !== projectRange) {
    report.issues.push({
      packagePath: 'package-lock.json#packages[""]',
      message: 'package-lock.json root engines.node must match package.json engines.node',
    })
  }

  for (const [packagePath, metadata] of Object.entries(lockedPackages)) {
    if (packagePath === '') continue
    const dependencyRange = metadata?.engines?.node
    if (typeof dependencyRange !== 'string') continue

    // Optional native/platform-specific packages are not installed on every supported Node target.
    if (metadata.optional === true) {
      report.skippedOptionalPackages += 1
      continue
    }

    report.checkedPackages += 1
    try {
      if (!semver.subset(projectRange, dependencyRange)) {
        report.issues.push({
          packagePath: packagePath || manifest.name || 'root package',
          dependencyRange,
          message: `${packagePath || manifest.name || 'root package'} requires Node ${dependencyRange}, which does not cover engines.node ${projectRange}`,
        })
      }
    } catch (error) {
      report.issues.push({
        packagePath,
        dependencyRange,
        message: `${packagePath || manifest.name || 'root package'} has an invalid Node engine range: ${error.message}`,
      })
    }
  }

  return report
}

function readJson(url) {
  return JSON.parse(readFileSync(url, 'utf8'))
}

function main() {
  const manifestUrl = new URL('../package.json', import.meta.url)
  const lockfileUrl = new URL('../package-lock.json', import.meta.url)
  const manifest = readJson(manifestUrl)
  const lockfile = readJson(lockfileUrl)
  const report = inspectNodeEngineCompatibility(manifest, lockfile)

  if (report.issues.length > 0) {
    console.error(`Node engine compatibility failed with ${report.issues.length} issue(s):`)
    for (const issue of report.issues) console.error(`- ${issue.message}`)
    process.exitCode = 1
    return
  }

  console.log(
    `Node engine compatibility passed (${process.version}; ${report.checkedPackages} required packages checked; ${report.skippedOptionalPackages} optional packages skipped).`,
  )
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
