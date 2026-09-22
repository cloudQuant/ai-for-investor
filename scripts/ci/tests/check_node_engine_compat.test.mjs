import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { describe, it } from 'node:test'
import { inspectNodeEngineCompatibility } from '../../../src/frontend/scripts/check-node-engine-compat.mjs'

const packageJson = JSON.parse(readFileSync(new URL('../../../src/frontend/package.json', import.meta.url), 'utf8'))
const packageLock = JSON.parse(readFileSync(new URL('../../../src/frontend/package-lock.json', import.meta.url), 'utf8'))
const SUPPORTED_RUNTIME = '20.20.2'

describe('frontend Node engine compatibility', () => {
  it('covers the current runtime and every required locked dependency engine range', () => {
    const report = inspectNodeEngineCompatibility(packageJson, packageLock, SUPPORTED_RUNTIME)

    assert.deepEqual(report.issues, [])
    assert.ok(report.checkedPackages > 0)
    assert.ok(report.skippedOptionalPackages > 0)
  })

  it('rejects the previous broad Node range when locked dependencies need newer minors', () => {
    const broadManifest = {
      ...packageJson,
      engines: { ...packageJson.engines, node: '>=20 <25' },
    }
    const report = inspectNodeEngineCompatibility(broadManifest, packageLock, SUPPORTED_RUNTIME)

    assert.ok(report.issues.some((issue) => issue.packagePath === 'node_modules/jsdom'))
    assert.ok(report.issues.some((issue) => issue.packagePath?.includes('@csstools/css-tokenizer')))
  })

  it('rejects a runtime below the declared minimum', () => {
    const report = inspectNodeEngineCompatibility(packageJson, packageLock, '20.18.0')

    assert.ok(report.issues.some((issue) => issue.message.includes('running Node 20.18.0')))
  })

  it('rejects Node 25 because production does not support it', () => {
    const report = inspectNodeEngineCompatibility(packageJson, packageLock, '25.1.0')

    assert.ok(report.issues.some((issue) => issue.message.includes('running Node 25.1.0')))
  })

  it('does not treat an optional native package as a universal runtime constraint', () => {
    const report = inspectNodeEngineCompatibility(
      { name: 'fixture', engines: { node: '^20.19.0 || ^22.13.0 || ^24.0.0' } },
      {
        packages: {
          '': { engines: { node: '^20.19.0 || ^22.13.0 || ^24.0.0' } },
          'node_modules/optional-native': {
            optional: true,
            engines: { node: '^22.20 || ^24.12 || >=25' },
          },
        },
      },
      '20.20.2',
    )

    assert.deepEqual(report.issues, [])
    assert.equal(report.checkedPackages, 0)
    assert.equal(report.skippedOptionalPackages, 1)
  })
})
