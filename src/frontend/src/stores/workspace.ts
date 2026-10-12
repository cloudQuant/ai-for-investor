import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { isSupersededSessionRequestError } from '@/api/index'
import { workspaceApi } from '@/api/workspace'
import type {
  Workspace,
  WorkspaceCreate,
  WorkspaceType,
  WorkspaceUpdate,
  StrategyUnit,
  StrategyUnitCreate,
  StrategyUnitUpdate,
  GroupRenameRequest,
  UnitRenameRequest,
  UnitStatusResponse,
} from '@/types/workspace'

function isOptimizationActiveStatus(status: string | null | undefined): boolean {
  return status === 'pending' || status === 'queued' || status === 'running'
}

function isOptimizationTerminalStatus(status: string | null | undefined): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}

function isSessionExpiredError(error: unknown): boolean {
  if (!error || typeof error !== 'object' || !('response' in error)) {
    return false
  }
  return (error as { response?: { status?: number } }).response?.status === 401
}

function mergeOptimizationRuntimeState(incoming: StrategyUnit, existing?: StrategyUnit): StrategyUnit {
  if (!existing) {
    return incoming
  }

  // If existing has a recently-started active optimization and incoming
  // does NOT report an active status, the backend is still returning stale
  // data (old task or not-yet-committed new task).  Preserve local state.
  const existingActive = isOptimizationActiveStatus(existing.opt_status)
  if (existingActive) {
    const startedAt = existing.opt_started_at_ms ?? 0
    const recentlyStarted = Date.now() - startedAt < 15000
    const preserveQueuedLocalState =
      recentlyStarted &&
      (existing.opt_status === 'pending' || existing.opt_status === 'queued') &&
      !isOptimizationActiveStatus(incoming.opt_status)
    if (preserveQueuedLocalState) {
      return {
        ...incoming,
        last_optimization_task_id: existing.last_optimization_task_id ?? incoming.last_optimization_task_id,
        opt_status: existing.opt_status,
        opt_total: existing.opt_total,
        opt_completed: existing.opt_completed,
        opt_progress: existing.opt_progress,
        opt_elapsed_time: existing.opt_elapsed_time,
        opt_remaining_time: existing.opt_remaining_time,
        opt_started_at_ms: existing.opt_started_at_ms,
        opt_last_sync_at_ms: existing.opt_last_sync_at_ms,
      }
    }
  }

  const incomingActive = isOptimizationActiveStatus(incoming.opt_status)
  // Otherwise use incoming data but carry over local timing fields
  return {
    ...incoming,
    opt_started_at_ms: incomingActive
      ? (existing.opt_started_at_ms ?? incoming.opt_started_at_ms ?? null)
      : (incoming.opt_started_at_ms ?? null),
    opt_last_sync_at_ms: incomingActive
      ? (existing.opt_last_sync_at_ms ?? incoming.opt_last_sync_at_ms ?? null)
      : (incoming.opt_last_sync_at_ms ?? null),
  }
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const workspaces = ref<Workspace[]>([])
  const currentWorkspace = ref<Workspace | null>(null)
  const units = ref<StrategyUnit[]>([])
  const selectedUnitIds = ref<string[]>([])
  const activeWorkspaceId = ref<string | null>(null)
  const listLoading = ref(false)
  const detailLoading = ref(false)
  const unitsLoading = ref(false)
  const loading = computed(() => listLoading.value || detailLoading.value || unitsLoading.value)
  const total = ref(0)
  let workspaceGeneration = 0
  let workspaceRequestGeneration = 0
  let unitsRequestGeneration = 0
  let workspacesRequestGeneration = 0

  function resetForSession() {
    workspaceGeneration += 1
    workspaceRequestGeneration += 1
    unitsRequestGeneration += 1
    workspacesRequestGeneration += 1
    workspaces.value = []
    currentWorkspace.value = null
    units.value = []
    selectedUnitIds.value = []
    activeWorkspaceId.value = null
    listLoading.value = false
    detailLoading.value = false
    unitsLoading.value = false
    total.value = 0
    running.value = false
    stopPolling()
  }

  function activateWorkspace(workspaceId: string) {
    if (activeWorkspaceId.value === workspaceId) {
      return
    }

    activeWorkspaceId.value = workspaceId
    workspaceGeneration += 1
    workspaceRequestGeneration += 1
    unitsRequestGeneration += 1
    currentWorkspace.value = null
    units.value = []
    selectedUnitIds.value = []
    detailLoading.value = false
    unitsLoading.value = false
    running.value = false
    stopPolling()
  }

  function ensureWorkspaceActive(workspaceId: string): boolean {
    if (activeWorkspaceId.value === null) {
      activateWorkspace(workspaceId)
    }
    return activeWorkspaceId.value === workspaceId
  }

  function isCurrentWorkspace(workspaceId: string, generation: number): boolean {
    return activeWorkspaceId.value === workspaceId && workspaceGeneration === generation
  }

  // ------------------------------------------------------------------
  // Workspace CRUD
  // ------------------------------------------------------------------

  async function fetchWorkspaces(skip = 0, limit = 50, workspaceType?: WorkspaceType) {
    const requestGeneration = ++workspacesRequestGeneration
    listLoading.value = true
    try {
      const res = await workspaceApi.list(skip, limit, workspaceType)
      if (requestGeneration === workspacesRequestGeneration) {
        workspaces.value = res.items
        total.value = res.total
      }
    } catch (error) {
      if (!isSupersededSessionRequestError(error) && !isSessionExpiredError(error)) {
        throw error
      }
    } finally {
      if (requestGeneration === workspacesRequestGeneration) {
        listLoading.value = false
      }
    }
  }

  async function fetchWorkspace(id: string) {
    if (!ensureWorkspaceActive(id)) {
      return null
    }

    const requestGeneration = ++workspaceRequestGeneration
    const resourceGeneration = workspaceGeneration
    detailLoading.value = true
    try {
      const workspace = await workspaceApi.get(id)
      if (requestGeneration === workspaceRequestGeneration && isCurrentWorkspace(id, resourceGeneration)) {
        currentWorkspace.value = workspace
        return workspace
      }
      return null
    } catch (error) {
      if (!isSupersededSessionRequestError(error) && !isSessionExpiredError(error)) {
        throw error
      }
      return null
    } finally {
      if (requestGeneration === workspaceRequestGeneration && isCurrentWorkspace(id, resourceGeneration)) {
        detailLoading.value = false
      }
    }
  }

  async function createWorkspace(data: WorkspaceCreate) {
    const ws = await workspaceApi.create(data)
    workspaces.value.unshift(ws)
    total.value++
    return ws
  }

  async function updateWorkspace(id: string, data: WorkspaceUpdate) {
    const ws = await workspaceApi.update(id, data)
    const idx = workspaces.value.findIndex(w => w.id === id)
    if (idx >= 0) workspaces.value[idx] = ws
    if (currentWorkspace.value?.id === id) currentWorkspace.value = ws
    return ws
  }

  async function deleteWorkspace(id: string) {
    await workspaceApi.delete(id)
    workspaces.value = workspaces.value.filter(w => w.id !== id)
    total.value--
    if (currentWorkspace.value?.id === id) currentWorkspace.value = null
  }

  // ------------------------------------------------------------------
  // Strategy Unit CRUD
  // ------------------------------------------------------------------

  async function fetchUnits(workspaceId: string) {
    if (!ensureWorkspaceActive(workspaceId)) {
      return
    }

    const requestGeneration = ++unitsRequestGeneration
    const resourceGeneration = workspaceGeneration
    unitsLoading.value = true
    try {
      const res = await workspaceApi.listUnits(workspaceId)
      if (requestGeneration !== unitsRequestGeneration || !isCurrentWorkspace(workspaceId, resourceGeneration)) {
        return
      }
      const existingMap = new Map(units.value.map(unit => [unit.id, unit]))
      units.value = res.items.map(unit => mergeOptimizationRuntimeState(unit, existingMap.get(unit.id)))
    } catch (error) {
      if (!isSupersededSessionRequestError(error) && !isSessionExpiredError(error)) {
        throw error
      }
    } finally {
      if (requestGeneration === unitsRequestGeneration && isCurrentWorkspace(workspaceId, resourceGeneration)) {
        unitsLoading.value = false
      }
    }
  }

  async function createUnit(workspaceId: string, data: StrategyUnitCreate) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    const unit = await workspaceApi.createUnit(workspaceId, data)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      units.value.push(unit)
    }
    return unit
  }

  async function batchCreateUnits(workspaceId: string, data: StrategyUnitCreate[]) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    const created = await workspaceApi.batchCreateUnits(workspaceId, data)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      units.value.push(...created)
    }
    return created
  }

  async function updateUnit(workspaceId: string, unitId: string, data: StrategyUnitUpdate) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    const unit = await workspaceApi.updateUnit(workspaceId, unitId, data)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      const idx = units.value.findIndex(u => u.id === unitId)
      if (idx >= 0) units.value[idx] = unit
    }
    return unit
  }

  async function patchUnits(workspaceId: string, unitIds: string[], data: StrategyUnitUpdate) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    const results = await Promise.all(unitIds.map(unitId => workspaceApi.updateUnit(workspaceId, unitId, data)))
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      const resultMap = new Map(results.map(unit => [unit.id, unit]))
      units.value = units.value.map(unit => resultMap.get(unit.id) ?? unit)
    }
    return results
  }

  async function deleteUnit(workspaceId: string, unitId: string) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    await workspaceApi.deleteUnit(workspaceId, unitId)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      units.value = units.value.filter(u => u.id !== unitId)
    }
  }

  async function bulkDeleteUnits(workspaceId: string, ids: string[]) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    const res = await workspaceApi.bulkDeleteUnits(workspaceId, { ids })
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      units.value = units.value.filter(u => !ids.includes(u.id))
      selectedUnitIds.value = selectedUnitIds.value.filter(id => !ids.includes(id))
    }
    return res.deleted
  }

  async function reorderUnits(workspaceId: string, unitIds: string[]) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    await workspaceApi.reorderUnits(workspaceId, { unit_ids: unitIds })
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      // Re-sort local array to match new order
      const orderMap = new Map(unitIds.map((id, i) => [id, i]))
      units.value.sort((a, b) => (orderMap.get(a.id) ?? 0) - (orderMap.get(b.id) ?? 0))
    }
  }

  async function renameGroup(workspaceId: string, data: GroupRenameRequest) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    await workspaceApi.renameGroup(workspaceId, data)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      await fetchUnits(workspaceId)
    }
  }

  async function renameUnit(workspaceId: string, data: UnitRenameRequest) {
    if (!ensureWorkspaceActive(workspaceId)) {
      throw new Error('Cannot update units for an inactive workspace.')
    }
    const resourceGeneration = workspaceGeneration
    await workspaceApi.renameUnit(workspaceId, data)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      await fetchUnits(workspaceId)
    }
  }

  // ------------------------------------------------------------------
  // Selection helpers
  // ------------------------------------------------------------------

  function setSelectedUnitIds(ids: string[]) {
    const currentIds = new Set(units.value.map(unit => unit.id))
    selectedUnitIds.value = [...new Set(ids)].filter(id => currentIds.has(id))
  }

  function clearSelection() {
    selectedUnitIds.value = []
  }

  // ------------------------------------------------------------------
  // Run orchestration (Phase 3)
  // ------------------------------------------------------------------

  const running = ref(false)
  const MAX_CONSECUTIVE_POLL_FAILURES = 3
  const MAX_POLL_BACKOFF_MS = 30_000
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let pollInFlight = false
  let pollInFlightGeneration: number | null = null
  let pollGeneration = 0
  let pollingWorkspaceId: string | null = null
  let pollingIntervalMs = 3000
  let consecutivePollFailures = 0

  async function runSelectedUnits(workspaceId: string, parallel = false) {
    if (!ensureWorkspaceActive(workspaceId)) return
    const resourceGeneration = workspaceGeneration
    const currentUnitIds = new Set(units.value.map(unit => unit.id))
    const selectedIds = selectedUnitIds.value.filter(id => currentUnitIds.has(id))
    if (!selectedIds.length) return
    running.value = true
    try {
      // Optimistically mark selected as queued
      for (const u of units.value) {
        if (selectedIds.includes(u.id)) {
          u.run_status = 'queued'
          u.run_progress = 0
          u.run_message = '回测任务排队中'
        }
      }
      const res = await workspaceApi.runUnits(workspaceId, selectedIds, parallel)
      if (!isCurrentWorkspace(workspaceId, resourceGeneration)) {
        return res.results
      }
      // Update local state from results
      for (const r of res.results) {
        const idx = units.value.findIndex(u => u.id === r.unit_id)
        if (idx >= 0) {
          units.value[idx].run_status = r.status as StrategyUnit['run_status']
          if (r.task_id) units.value[idx].last_task_id = r.task_id
          units.value[idx].run_progress = r.status === 'running' ? 10 : 0
          units.value[idx].run_message = r.status === 'running' ? '回测任务已提交' : r.error ?? null
        }
      }
      return res.results
    } finally {
      if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
        running.value = false
        // A timed-out submission may already have been accepted by the backend.
        // Resume this workspace status stream to reconcile its final state.
        startPolling(workspaceId)
      }
    }
  }

  async function stopSelectedUnits(workspaceId: string) {
    if (!ensureWorkspaceActive(workspaceId)) return
    const resourceGeneration = workspaceGeneration
    const currentUnitIds = new Set(units.value.map(unit => unit.id))
    const selectedIds = selectedUnitIds.value.filter(id => currentUnitIds.has(id))
    if (!selectedIds.length) return
    await workspaceApi.stopUnits(workspaceId, selectedIds)
    if (isCurrentWorkspace(workspaceId, resourceGeneration)) {
      await fetchUnits(workspaceId)
    }
  }

  function hasActiveUnitRuns(): boolean {
    return units.value.some(unit => {
      const snapshotStatus = String(unit.trading_snapshot?.instance_status ?? '').toLowerCase()
      return ['queued', 'running'].includes(unit.run_status)
        || ['queued', 'starting', 'running', 'live', 'connected'].includes(snapshotStatus)
    })
  }

  async function pollStatus(workspaceId: string): Promise<boolean> {
    if (!ensureWorkspaceActive(workspaceId)) return false
    const resourceGeneration = workspaceGeneration
    if (pollInFlight && pollInFlightGeneration === resourceGeneration) return false
    pollInFlight = true
    pollInFlightGeneration = resourceGeneration
    try {
      const statuses: UnitStatusResponse[] = await workspaceApi.getUnitsStatus(workspaceId)
      if (!isCurrentWorkspace(workspaceId, resourceGeneration)) {
        return false
      }
      const now = Date.now()
      for (const s of statuses) {
        const idx = units.value.findIndex(u => u.id === s.id)
        if (idx >= 0) {
          const unit = units.value[idx]

          // Always update non-optimization fields
          unit.run_status = s.run_status
          unit.last_task_id = s.last_task_id
          unit.error_message = s.error_message
          unit.metrics_snapshot = s.metrics_snapshot
          unit.run_progress = s.run_progress
          unit.run_message = s.run_message
          unit.run_count = s.run_count
          unit.last_run_time = s.last_run_time
          unit.bar_count = s.bar_count
          unit.trading_instance_id = s.trading_instance_id
          unit.trading_snapshot = s.trading_snapshot
          unit.trading_mode = s.trading_mode
          unit.lock_trading = s.lock_trading
          unit.lock_running = s.lock_running

          // Bug8 protection: if local has a recently-started active optimization
          // but backend returns stale/terminal/null (e.g. because the submission
          // hasn't been committed to the DB yet or the unit is still waiting in
          // a batch queue), preserve the locally-initialized pending state so the
          // UI doesn't flip back to "已完成".  For units still waiting in the batch
          // queue, refresh opt_started_at_ms to "now" so the elapsed clock stays
          // at zero until the unit actually starts running.
          const localActive = isOptimizationActiveStatus(unit.opt_status)
          const incomingTotal = Math.max(0, Number(s.opt_total ?? 0))
          const incomingCompleted = Math.max(0, Number(s.opt_completed ?? 0))
          const prematureCompleted =
            s.opt_status === 'completed' &&
            incomingTotal > 0 &&
            incomingCompleted < incomingTotal

          if (localActive && prematureCompleted) {
            continue
          }

          const preserveQueuedLocalState =
            localActive &&
            (unit.opt_status === 'pending' || unit.opt_status === 'queued') &&
            !isOptimizationActiveStatus(s.opt_status)
          if (preserveQueuedLocalState) {
            const startedAt = unit.opt_started_at_ms ?? 0
            if (now - startedAt < 15000) {
              unit.opt_started_at_ms = now
              unit.opt_elapsed_time = 0
              unit.opt_remaining_time = 0
              continue
            }
          }

          const preserveRunningLocalState =
            unit.opt_status === 'running' &&
            !isOptimizationTerminalStatus(s.opt_status) &&
            !isOptimizationActiveStatus(s.opt_status)
          if (preserveRunningLocalState) {
            const lastSyncAt = unit.opt_last_sync_at_ms ?? unit.opt_started_at_ms ?? 0
            if (now - lastSyncAt < 10000) {
              continue
            }
          }

          unit.opt_status = s.opt_status
          unit.opt_total = s.opt_total
          unit.opt_completed = s.opt_completed
          unit.opt_progress = s.opt_progress
          unit.opt_elapsed_time = s.opt_elapsed_time
          unit.opt_remaining_time = s.opt_remaining_time
          unit.opt_last_sync_at_ms = now
          if (s.opt_status === 'running') {
            // Backend reports running: trust its elapsed as ground truth and
            // recompute opt_started_at_ms so the frontend live clock is aligned.
            const baseElapsed = Math.max(0, s.opt_elapsed_time ?? 0)
            unit.opt_started_at_ms = now - Math.round(baseElapsed * 1000)
          } else if (s.opt_status === 'pending' || s.opt_status === 'queued') {
            // Backend reports pending/queued: keep the clock at zero.
            unit.opt_started_at_ms = now
            unit.opt_elapsed_time = 0
            unit.opt_remaining_time = 0
          } else if (s.opt_status) {
            unit.opt_started_at_ms = null
            unit.opt_last_sync_at_ms = null
            unit.opt_remaining_time = 0
          } else if (s.opt_status == null) {
            unit.opt_started_at_ms = null
            unit.opt_last_sync_at_ms = null
          }
        }
      }
      return true
    } catch {
      // Silently ignore poll failures
      return false
    } finally {
      if (pollInFlightGeneration === resourceGeneration) {
        pollInFlight = false
        pollInFlightGeneration = null
      }
    }
  }

  function startPolling(workspaceId: string, intervalMs = 3000) {
    if (!ensureWorkspaceActive(workspaceId)) return
    stopPolling()
    pollingWorkspaceId = workspaceId
    pollingIntervalMs = intervalMs
    consecutivePollFailures = 0
    const generation = pollGeneration

    const scheduleNext = (delay: number) => {
      pollTimer = setTimeout(() => {
        void pollOnce()
      }, delay)
    }

    const pollOnce = async () => {
      const succeeded = await pollStatus(workspaceId)
      if (
        generation !== pollGeneration
        || pollingWorkspaceId !== workspaceId
        || activeWorkspaceId.value !== workspaceId
      ) return

      if (!succeeded) {
        consecutivePollFailures += 1
        if (consecutivePollFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          pollTimer = null
          return
        }
        const delay = Math.min(
          pollingIntervalMs * 2 ** consecutivePollFailures,
          MAX_POLL_BACKOFF_MS,
        )
        scheduleNext(delay)
        return
      }

      consecutivePollFailures = 0
      // Initial page hydration and the status request race each other.  Keep
      // one follow-up poll while the unit list is still empty, then stop after
      // terminal states so a failed launch cannot create an endless request loop.
      if (units.value.length > 0 && !hasActiveUnitRuns()) {
        pollTimer = null
        return
      }
      scheduleNext(pollingIntervalMs)
    }

    void pollOnce()
  }

  function stopPolling() {
    pollGeneration += 1
    pollingWorkspaceId = null
    consecutivePollFailures = 0
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  return {
    workspaces,
    currentWorkspace,
    units,
    selectedUnitIds,
    activeWorkspaceId,
    resetForSession,
    activateWorkspace,
    loading,
    total,
    running,
    fetchWorkspaces,
    fetchWorkspace,
    createWorkspace,
    updateWorkspace,
    deleteWorkspace,
    fetchUnits,
    createUnit,
    batchCreateUnits,
    updateUnit,
    patchUnits,
    deleteUnit,
    bulkDeleteUnits,
    reorderUnits,
    renameGroup,
    renameUnit,
    setSelectedUnitIds,
    clearSelection,
    runSelectedUnits,
    stopSelectedUnits,
    pollStatus,
    startPolling,
    stopPolling,
  }
})
