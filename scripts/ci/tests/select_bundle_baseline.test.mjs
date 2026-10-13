import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, it } from 'node:test'
import { fileURLToPath } from 'node:url'
import { selectArtifact, selectRun } from '../select_bundle_baseline.mjs'

const BASE_BRANCH = 'dev'
const BASE_SHA = 'a'.repeat(40)
const helperPath = fileURLToPath(new URL('../select_bundle_baseline.mjs', import.meta.url))
const temporaryRoots = []

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true })
})

function workflowRun({
  id,
  runNumber = id,
  branch = BASE_BRANCH,
  sha = BASE_SHA,
  event = 'push',
  status = 'completed',
  conclusion = 'success',
}) {
  return {
    id,
    run_number: runNumber,
    head_branch: branch,
    head_sha: sha,
    event,
    status,
    conclusion,
  }
}

describe('bundle baseline workflow run selection', () => {
  it('selects the newest successful push or manual run for the exact target ref and SHA', () => {
    const runs = [
      workflowRun({ id: 20, runNumber: 20 }),
      workflowRun({ id: 21, runNumber: 21, event: 'workflow_dispatch' }),
      workflowRun({ id: 22, runNumber: 22, branch: 'master' }),
      workflowRun({ id: 23, runNumber: 23, sha: 'b'.repeat(40) }),
      workflowRun({ id: 24, runNumber: 24, event: 'pull_request' }),
      workflowRun({ id: 25, runNumber: 25, conclusion: 'failure' }),
      workflowRun({ id: 26, runNumber: 26, status: 'in_progress' }),
    ]

    assert.equal(selectRun(runs, BASE_BRANCH, BASE_SHA)?.id, 21)
  })

  it('does not use another branch, SHA, PR run, or failed run as a baseline', () => {
    const runs = [
      workflowRun({ id: 22, branch: 'master' }),
      workflowRun({ id: 23, sha: 'b'.repeat(40) }),
      workflowRun({ id: 24, event: 'pull_request' }),
      workflowRun({ id: 25, conclusion: 'failure' }),
    ]

    assert.equal(selectRun(runs, BASE_BRANCH, BASE_SHA), null)
  })
})

describe('bundle baseline artifact selection', () => {
  it('selects only an unexpired frontend-dist artifact belonging to the selected run', () => {
    const artifacts = [
      { id: 30, name: 'frontend-dist', expired: false, workflow_run: { id: 20 } },
      { id: 31, name: 'frontend-dist', expired: true, workflow_run: { id: 21 } },
      { id: 32, name: 'backend-report', expired: false, workflow_run: { id: 21 } },
      { id: 33, name: 'frontend-dist', expired: false, workflow_run: { id: 21 } },
    ]

    assert.equal(selectArtifact(artifacts, 21)?.id, 33)
  })

  it('treats a missing artifact as no baseline and rejects ambiguous duplicates', () => {
    assert.equal(selectArtifact([], 21), null)
    assert.throws(
      () => selectArtifact([
        { id: 33, name: 'frontend-dist', expired: false, workflow_run: { id: 21 } },
        { id: 34, name: 'frontend-dist', expired: false, workflow_run: { id: 21 } },
      ], 21),
      /expected at most one frontend-dist artifact/,
    )
  })

  it('exposes the selected run and artifact IDs through the workflow CLI contract', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bundle-baseline-api-'))
    temporaryRoots.push(root)
    const runsPath = path.join(root, 'runs.json')
    const artifactsPath = path.join(root, 'artifacts.json')
    fs.writeFileSync(runsPath, JSON.stringify({ workflow_runs: [workflowRun({ id: 41, runNumber: 41 })] }))
    fs.writeFileSync(artifactsPath, JSON.stringify({ artifacts: [
      { id: 51, name: 'frontend-dist', expired: false, workflow_run: { id: 41 } },
    ] }))

    const secondRunsPath = path.join(root, 'dispatch-runs.json')
    fs.writeFileSync(secondRunsPath, JSON.stringify({ workflow_runs: [
      workflowRun({ id: 42, runNumber: 42, event: 'workflow_dispatch' }),
    ] }))

    const run = spawnSync(process.execPath, [
      helperPath, 'run', BASE_BRANCH, BASE_SHA, runsPath, secondRunsPath,
    ], { encoding: 'utf8' })
    const artifact = spawnSync(process.execPath, [helperPath, 'artifact', artifactsPath, '41'], { encoding: 'utf8' })
    assert.equal(run.status, 0, run.stderr)
    assert.equal(run.stdout, '42')
    assert.equal(artifact.status, 0, artifact.stderr)
    assert.equal(artifact.stdout, '51')
  })
})
