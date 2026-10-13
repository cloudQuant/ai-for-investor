#!/usr/bin/env node
// Select only a successful CI artifact produced by push/workflow_dispatch on
// the exact target branch commit. The workflow-runs list is fetched from the
// workflow-scoped API endpoint in ci.yml.

import fs from 'node:fs'
import { pathToFileURL } from 'node:url'

const ARTIFACT_NAME = 'frontend-dist'
const BASELINE_EVENTS = new Set(['push', 'workflow_dispatch'])

function positiveSafeInteger(value) {
  return Number.isSafeInteger(value) && value > 0
}

function selectRun(workflowRuns, baseBranch, baseSha) {
  if (!Array.isArray(workflowRuns)) throw new Error('workflow_runs must be an array')

  const candidates = workflowRuns.filter((run) => (
    run
    && run.head_branch === baseBranch
    && run.head_sha === baseSha
    && BASELINE_EVENTS.has(run.event)
    && run.status === 'completed'
    && run.conclusion === 'success'
    && positiveSafeInteger(run.id)
    && positiveSafeInteger(run.run_number)
  ))

  candidates.sort((left, right) => right.run_number - left.run_number || right.id - left.id)
  return candidates[0] || null
}

function selectArtifact(artifacts, runId) {
  if (!Array.isArray(artifacts)) throw new Error('artifacts must be an array')

  const matches = artifacts.filter((artifact) => (
    artifact
    && artifact.name === ARTIFACT_NAME
    && artifact.expired === false
    && positiveSafeInteger(artifact.id)
    && artifact.workflow_run
    && String(artifact.workflow_run.id) === String(runId)
  ))
  if (matches.length > 1) {
    throw new Error(`expected at most one ${ARTIFACT_NAME} artifact for workflow run ${runId}, found ${matches.length}`)
  }
  return matches[0] || null
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function main(argv) {
  const [mode, ...args] = argv.slice(2)
  if (mode === 'run' && args.length >= 3) {
    const [baseBranch, baseSha, ...workflowRunPaths] = args
    const payloads = workflowRunPaths.map(readJson)
    const workflowRuns = payloads.flatMap((payload) => {
      if (!Array.isArray(payload.workflow_runs)) throw new Error('workflow_runs must be an array')
      return payload.workflow_runs
    })
    const run = selectRun(workflowRuns, baseBranch, baseSha)
    if (run) process.stdout.write(String(run.id))
    return
  }
  if (mode === 'artifact' && args.length === 2) {
    const [jsonPath, runId] = args
    const payload = readJson(jsonPath)
    const artifact = selectArtifact(payload.artifacts, runId)
    if (artifact) process.stdout.write(String(artifact.id))
    return
  }
  throw new Error(
    'Usage: select_bundle_baseline.mjs run <base-branch> <base-sha> <workflow-runs.json> [<more-runs.json> ...] '
      + '| artifact <artifacts.json> <workflow-run-id>',
  )
}

const invokedPath = process.argv[1]
if (invokedPath && pathToFileURL(invokedPath).href === import.meta.url) {
  try {
    main(process.argv)
  } catch (error) {
    console.error(`ERROR: ${error.message}`)
    process.exitCode = 1
  }
}

export { selectArtifact, selectRun }
