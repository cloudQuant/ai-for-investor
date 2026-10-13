/**
 * Unit tests for src/stores/workspace.ts (Pinia store).
 *
 * Targets the public CRUD/selection/state-transition surface; deep
 * coverage of the optimization-state merging logic is exercised via a
 * focused subset of fetchUnits cases that simulate stale backend data.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useWorkspaceStore } from '@/stores/workspace'
import { workspaceApi } from '@/api/workspace'
import type { StrategyUnit, Workspace } from '@/types/workspace'

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    listUnits: vi.fn(),
    createUnit: vi.fn(),
    batchCreateUnits: vi.fn(),
    updateUnit: vi.fn(),
    patchUnits: vi.fn(),
    deleteUnit: vi.fn(),
    bulkDeleteUnits: vi.fn(),
    reorderUnits: vi.fn(),
    renameGroup: vi.fn(),
    renameUnit: vi.fn(),
    runUnits: vi.fn(),
    stopUnits: vi.fn(),
    getUnitsStatus: vi.fn(),
  },
}))

const baseWs = {
  id: 'ws-1',
  name: 'workspace 1',
  description: 'desc',
  workspace_type: 'research',
  settings: {},
  created_at: '2024-01-01T00:00:00',
  updated_at: '2024-01-01T00:00:00',
} as unknown as Workspace

const baseUnit = {
  id: 'u-1',
  workspace_id: 'ws-1',
  strategy_id: 's-1',
  strategy_name: 'sample',
  symbol_code: 'TEST',
  timeframe: '1d',
  category: 'trend',
  params: {},
  data_source: { type: 'csv' },
  backtest_defaults: {
    start_date: '2024-01-01', end_date: '2024-12-31',
    initial_cash: 100000, commission: 0.001,
  },
  optimization: null,
  run_status: 'idle',
  trading_mode: 'paper',
  lock_running: false,
  lock_trading: false,
  sort_order: 0,
  created_at: '2024-01-01T00:00:00',
  updated_at: '2024-01-01T00:00:00',
  trading_snapshot: null,
  opt_status: null,
  opt_started_at_ms: null,
  opt_last_sync_at_ms: null,
  last_optimization_task_id: null,
} as unknown as StrategyUnit

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('useWorkspaceStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    Object.values(workspaceApi).forEach(fn => (fn as any).mockReset?.())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('Workspace CRUD', () => {
    it('fetchWorkspaces populates list and total', async () => {
      vi.mocked(workspaceApi.list).mockResolvedValue({
        items: [baseWs], total: 1,
      })
      const store = useWorkspaceStore()
      await store.fetchWorkspaces()
      expect(store.workspaces).toHaveLength(1)
      expect(store.total).toBe(1)
      expect(store.loading).toBe(false)
    })

    it('fetchWorkspaces accepts skip/limit/workspaceType', async () => {
      vi.mocked(workspaceApi.list).mockResolvedValue({ items: [], total: 0 })
      const store = useWorkspaceStore()
      await store.fetchWorkspaces(10, 25, 'trading')
      expect(workspaceApi.list).toHaveBeenCalledWith(10, 25, 'trading')
    })

    it('fetchWorkspace sets currentWorkspace', async () => {
      vi.mocked(workspaceApi.get).mockResolvedValue(baseWs)
      const store = useWorkspaceStore()
      await store.fetchWorkspace('ws-1')
      expect(store.currentWorkspace).toEqual(baseWs)
    })

    it('keeps detail, units, selection, and loading bound to the active workspace', async () => {
      const detailA = deferred<Workspace>()
      const detailB = deferred<Workspace>()
      const unitsA = deferred<{ items: StrategyUnit[]; total: number }>()
      const unitsB = deferred<{ items: StrategyUnit[]; total: number }>()
      vi.mocked(workspaceApi.get).mockImplementation((id: string) => (
        (id === 'workspace-a' ? detailA.promise : detailB.promise) as never
      ))
      vi.mocked(workspaceApi.listUnits).mockImplementation((id: string) => (
        (id === 'workspace-a' ? unitsA.promise : unitsB.promise) as never
      ))

      const store = useWorkspaceStore()
      store.activateWorkspace('workspace-a')
      const detailARequest = store.fetchWorkspace('workspace-a')
      const unitsARequest = store.fetchUnits('workspace-a')
      store.units = [{ ...baseUnit, id: 'unit-a', workspace_id: 'workspace-a' }]
      store.setSelectedUnitIds(['unit-a'])

      store.activateWorkspace('workspace-b')
      expect(store.currentWorkspace).toBeNull()
      expect(store.units).toEqual([])
      expect(store.selectedUnitIds).toEqual([])
      const detailBRequest = store.fetchWorkspace('workspace-b')
      const unitsBRequest = store.fetchUnits('workspace-b')

      detailB.resolve({ ...baseWs, id: 'workspace-b', name: 'Beta' })
      await detailBRequest
      expect(store.currentWorkspace?.name).toBe('Beta')
      expect(store.loading).toBe(true)

      detailA.resolve({ ...baseWs, id: 'workspace-a', name: 'Alpha' })
      unitsA.resolve({
        items: [{ ...baseUnit, id: 'unit-a', workspace_id: 'workspace-a' }],
        total: 1,
      })
      await Promise.all([detailARequest, unitsARequest])
      expect(store.currentWorkspace?.id).toBe('workspace-b')
      expect(store.units).toEqual([])
      expect(store.loading).toBe(true)

      unitsB.resolve({
        items: [{ ...baseUnit, id: 'unit-b', workspace_id: 'workspace-b' }],
        total: 1,
      })
      await unitsBRequest
      expect(store.units.map(unit => unit.id)).toEqual(['unit-b'])
      expect(store.loading).toBe(false)

      store.setSelectedUnitIds(['unit-a', 'unit-b'])
      vi.mocked(workspaceApi.runUnits).mockResolvedValue({ results: [] } as never)
      await store.runSelectedUnits('workspace-a')
      expect(workspaceApi.runUnits).not.toHaveBeenCalled()
      await store.runSelectedUnits('workspace-b')
      expect(workspaceApi.runUnits).toHaveBeenCalledWith('workspace-b', ['unit-b'], false)
      store.stopPolling()
    })

    it('createWorkspace creates and returns the new workspace', async () => {
      vi.mocked(workspaceApi.create).mockResolvedValue(baseWs)
      vi.mocked(workspaceApi.list).mockResolvedValue({ items: [baseWs], total: 1 })
      const store = useWorkspaceStore()
      const created = await store.createWorkspace({ name: 'workspace 1' } as any)
      expect(created).toEqual(baseWs)
      expect(workspaceApi.create).toHaveBeenCalled()
    })

    it('updateWorkspace updates and refreshes state', async () => {
      const updated = { ...baseWs, name: 'renamed' }
      vi.mocked(workspaceApi.update).mockResolvedValue(updated)
      vi.mocked(workspaceApi.list).mockResolvedValue({ items: [updated], total: 1 })
      const store = useWorkspaceStore()
      const result = await store.updateWorkspace('ws-1', { name: 'renamed' } as any)
      expect(result).toEqual(updated)
    })

    it('deleteWorkspace deletes via API and refreshes the list', async () => {
      vi.mocked(workspaceApi.delete).mockResolvedValue(undefined as never)
      vi.mocked(workspaceApi.list).mockResolvedValue({ items: [], total: 0 })
      const store = useWorkspaceStore()
      await store.deleteWorkspace('ws-1')
      expect(workspaceApi.delete).toHaveBeenCalledWith('ws-1')
    })
  })

  describe('Unit CRUD', () => {
    it('fetchUnits sets units array and merges optimization state', async () => {
      vi.mocked(workspaceApi.listUnits).mockResolvedValue({ items: [baseUnit], total: 1 })
      const store = useWorkspaceStore()
      await store.fetchUnits('ws-1')
      expect(store.units).toHaveLength(1)
      expect(store.units[0].id).toBe('u-1')
    })

    it('createUnit creates and refreshes unit list', async () => {
      vi.mocked(workspaceApi.createUnit).mockResolvedValue(baseUnit)
      vi.mocked(workspaceApi.listUnits).mockResolvedValue({ items: [baseUnit], total: 1 })
      const store = useWorkspaceStore()
      const created = await store.createUnit('ws-1', {} as any)
      expect(created).toEqual(baseUnit)
    })

    it('batchCreateUnits creates multiple units', async () => {
      vi.mocked(workspaceApi.batchCreateUnits).mockResolvedValue([baseUnit, baseUnit])
      const store = useWorkspaceStore()
      await store.batchCreateUnits('ws-1', [{} as any])
      expect(workspaceApi.batchCreateUnits).toHaveBeenCalledWith('ws-1', [{}])
    })

    it('updateUnit updates and refreshes', async () => {
      vi.mocked(workspaceApi.updateUnit).mockResolvedValue(baseUnit)
      const store = useWorkspaceStore()
      // Pre-populate units so the index lookup finds the unit
      vi.mocked(workspaceApi.listUnits).mockResolvedValue({ items: [baseUnit], total: 1 })
      await store.fetchUnits('ws-1')
      await store.updateUnit('ws-1', 'u-1', {} as any)
      expect(workspaceApi.updateUnit).toHaveBeenCalledWith('ws-1', 'u-1', {})
    })

    it('patchUnits patches multiple units in parallel', async () => {
      vi.mocked(workspaceApi.updateUnit).mockResolvedValue(baseUnit)
      const store = useWorkspaceStore()
      const results = await store.patchUnits('ws-1', ['u-1', 'u-2'], {} as any)
      // Each unit calls updateUnit
      expect(workspaceApi.updateUnit).toHaveBeenCalledTimes(2)
      expect(results).toHaveLength(2)
    })

    it('deleteUnit removes single unit and refreshes', async () => {
      vi.mocked(workspaceApi.deleteUnit).mockResolvedValue(undefined as never)
      const store = useWorkspaceStore()
      await store.deleteUnit('ws-1', 'u-1')
      expect(workspaceApi.deleteUnit).toHaveBeenCalledWith('ws-1', 'u-1')
    })

    it('bulkDeleteUnits removes multiple units', async () => {
      vi.mocked(workspaceApi.bulkDeleteUnits).mockResolvedValue({ deleted: 2 } as never)
      const store = useWorkspaceStore()
      const result = await store.bulkDeleteUnits('ws-1', ['u-1', 'u-2'])
      expect(workspaceApi.bulkDeleteUnits).toHaveBeenCalledWith('ws-1', { ids: ['u-1', 'u-2'] })
      expect(result).toBe(2)
    })

    it('reorderUnits delegates to API with unit_ids body', async () => {
      vi.mocked(workspaceApi.reorderUnits).mockResolvedValue(undefined as never)
      const store = useWorkspaceStore()
      await store.reorderUnits('ws-1', ['u-1'])
      expect(workspaceApi.reorderUnits).toHaveBeenCalledWith('ws-1', { unit_ids: ['u-1'] })
    })

    it('renameGroup delegates to API and refetches units', async () => {
      vi.mocked(workspaceApi.renameGroup).mockResolvedValue(undefined as never)
      vi.mocked(workspaceApi.listUnits).mockResolvedValue({ items: [baseUnit], total: 1 })
      const store = useWorkspaceStore()
      await store.renameGroup('ws-1', { old_group: 'a', new_group: 'b' } as any)
      expect(workspaceApi.renameGroup).toHaveBeenCalled()
      expect(workspaceApi.listUnits).toHaveBeenCalled()
    })

    it('renameUnit delegates to API and refetches units', async () => {
      vi.mocked(workspaceApi.renameUnit).mockResolvedValue(undefined as never)
      vi.mocked(workspaceApi.listUnits).mockResolvedValue({ items: [baseUnit], total: 1 })
      const store = useWorkspaceStore()
      await store.renameUnit('ws-1', { unit_id: 'u-1', new_name: 'x' } as any)
      expect(workspaceApi.renameUnit).toHaveBeenCalled()
      expect(workspaceApi.listUnits).toHaveBeenCalled()
    })
  })

  describe('Selection', () => {
    it('setSelectedUnitIds replaces the array', () => {
      const store = useWorkspaceStore()
      store.units = [baseUnit, { ...baseUnit, id: 'u-2' }]
      store.setSelectedUnitIds(['u-1', 'u-2'])
      expect(store.selectedUnitIds).toEqual(['u-1', 'u-2'])
    })

    it('clearSelection empties the array', () => {
      const store = useWorkspaceStore()
      store.setSelectedUnitIds(['u-1'])
      store.clearSelection()
      expect(store.selectedUnitIds).toEqual([])
    })
  })

  describe('Status polling', () => {
    it('waits for an in-flight status request before scheduling the next poll', async () => {
      vi.useFakeTimers()
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, run_status: 'running' }]

      let resolveFirstPoll: ((value: any) => void) | undefined
      vi.mocked(workspaceApi.getUnitsStatus).mockImplementationOnce(
        () => new Promise(resolve => { resolveFirstPoll = resolve }) as never,
      )
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([
        { id: 'u-1', run_status: 'running' },
      ] as never)

      store.startPolling('ws-1', 3000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(12_000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)

      resolveFirstPoll?.([{ id: 'u-1', run_status: 'running' }])
      await vi.advanceTimersByTimeAsync(3000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(2)
      store.stopPolling()
    })

    it('stops after a successful terminal-status refresh', async () => {
      vi.useFakeTimers()
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, run_status: 'queued' }]
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([
        { id: 'u-1', run_status: 'failed' },
      ] as never)

      store.startPolling('ws-1', 3000)
      await vi.advanceTimersByTimeAsync(12_000)

      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)
      store.stopPolling()
    })
  })

  describe('request and account boundaries', () => {
    it('only applies the latest workspace-list request and keeps its loading state until it settles', async () => {
      const older = deferred<{ items: Workspace[]; total: number }>()
      const newer = deferred<{ items: Workspace[]; total: number }>()
      vi.mocked(workspaceApi.list)
        .mockReturnValueOnce(older.promise as never)
        .mockReturnValueOnce(newer.promise as never)
      const store = useWorkspaceStore()

      const oldRequest = store.fetchWorkspaces(0, 10)
      const newRequest = store.fetchWorkspaces(10, 10, 'trading')
      expect(workspaceApi.list).toHaveBeenNthCalledWith(1, 0, 10, undefined)
      expect(workspaceApi.list).toHaveBeenNthCalledWith(2, 10, 10, 'trading')

      newer.resolve({ items: [{ ...baseWs, id: 'new' }], total: 7 })
      await newRequest
      expect(store.workspaces.map(workspace => workspace.id)).toEqual(['new'])
      expect(store.total).toBe(7)
      expect(store.loading).toBe(false)

      older.resolve({ items: [{ ...baseWs, id: 'old' }], total: 1 })
      await oldRequest
      expect(store.workspaces.map(workspace => workspace.id)).toEqual(['new'])
      expect(store.total).toBe(7)
    })

    it('rethrows list failures and resets list loading', async () => {
      vi.mocked(workspaceApi.list).mockRejectedValueOnce(new Error('workspace service unavailable'))
      const store = useWorkspaceStore()

      await expect(store.fetchWorkspaces()).rejects.toThrow('workspace service unavailable')

      expect(workspaceApi.list).toHaveBeenCalledWith(0, 50, undefined)
      expect(store.workspaces).toEqual([])
      expect(store.loading).toBe(false)
    })

    it('swallows expired-session detail and unit reads but propagates ordinary service failures', async () => {
      const store = useWorkspaceStore()
      vi.mocked(workspaceApi.get).mockRejectedValueOnce({ response: { status: 401 } })
      expect(await store.fetchWorkspace('ws-1')).toBeNull()
      expect(store.currentWorkspace).toBeNull()
      expect(store.loading).toBe(false)

      vi.mocked(workspaceApi.listUnits).mockRejectedValueOnce({ response: { status: 401 } })
      await store.fetchUnits('ws-1')
      expect(store.units).toEqual([])
      expect(store.loading).toBe(false)

      vi.mocked(workspaceApi.get).mockRejectedValueOnce(new Error('detail failed'))
      await expect(store.fetchWorkspace('ws-1')).rejects.toThrow('detail failed')
      expect(store.loading).toBe(false)

      vi.mocked(workspaceApi.listUnits).mockRejectedValueOnce(new Error('units failed'))
      await expect(store.fetchUnits('ws-1')).rejects.toThrow('units failed')
      expect(store.loading).toBe(false)
    })

    it('invalidates a pending account request when the session is reset', async () => {
      const pending = deferred<Workspace>()
      vi.mocked(workspaceApi.get).mockReturnValueOnce(pending.promise as never)
      const store = useWorkspaceStore()
      const request = store.fetchWorkspace('ws-account-a')
      expect(store.activeWorkspaceId).toBe('ws-account-a')
      expect(store.loading).toBe(true)

      store.workspaces = [baseWs]
      store.units = [baseUnit]
      store.setSelectedUnitIds(['u-1'])
      store.resetForSession()
      pending.resolve({ ...baseWs, id: 'ws-account-a' })
      await request

      expect(store.workspaces).toEqual([])
      expect(store.currentWorkspace).toBeNull()
      expect(store.units).toEqual([])
      expect(store.selectedUnitIds).toEqual([])
      expect(store.activeWorkspaceId).toBeNull()
      expect(store.total).toBe(0)
      expect(store.loading).toBe(false)
    })

    it('keeps workspace totals and selected detail consistent during create, update, and delete', async () => {
      const store = useWorkspaceStore()
      store.workspaces = [baseWs]
      store.total = 1
      store.currentWorkspace = baseWs
      const created = { ...baseWs, id: 'ws-2', name: 'second' }
      vi.mocked(workspaceApi.create).mockResolvedValueOnce(created)
      expect(await store.createWorkspace({ name: 'second' } as never)).toEqual(created)
      expect(workspaceApi.create).toHaveBeenCalledWith({ name: 'second' })
      expect(store.workspaces.map(workspace => workspace.id)).toEqual(['ws-2', 'ws-1'])
      expect(store.total).toBe(2)

      const updated = { ...baseWs, name: 'renamed' }
      vi.mocked(workspaceApi.update).mockResolvedValueOnce(updated)
      await store.updateWorkspace('ws-1', { name: 'renamed' } as never)
      expect(store.workspaces[1].name).toBe('renamed')
      expect(store.currentWorkspace?.name).toBe('renamed')

      vi.mocked(workspaceApi.update).mockResolvedValueOnce({ ...created, name: 'updated but not selected' })
      const selected = store.currentWorkspace
      await store.updateWorkspace('missing', { name: 'ignored' } as never)
      expect(store.currentWorkspace).toBe(selected)

      vi.mocked(workspaceApi.delete).mockResolvedValueOnce(undefined as never)
      await store.deleteWorkspace('ws-1')
      expect(workspaceApi.delete).toHaveBeenCalledWith('ws-1')
      expect(store.workspaces.map(workspace => workspace.id)).toEqual(['ws-2'])
      expect(store.currentWorkspace).toBeNull()
      expect(store.total).toBe(1)
    })

    it('keeps pending local optimization state when a just-started backend snapshot is stale', async () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-10-13T00:00:10.000Z'))
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{
        ...baseUnit, opt_status: 'queued', opt_total: 20, opt_completed: 3,
        opt_progress: 15, opt_elapsed_time: 0, opt_remaining_time: 0,
        opt_started_at_ms: Date.now() - 1000, last_optimization_task_id: 'task-1',
      }]
      vi.mocked(workspaceApi.listUnits).mockResolvedValueOnce({ items: [{
        ...baseUnit, opt_status: null,
      }], total: 1 })

      await store.fetchUnits('ws-1')

      expect(store.units[0]).toMatchObject({
        opt_status: 'queued', opt_total: 20, opt_completed: 3, opt_progress: 15,
        last_optimization_task_id: 'task-1',
      })
      expect(store.units[0].opt_started_at_ms).toBe(Date.now() - 1000)
    })

    it('uses incoming active optimization status while carrying local timing, then accepts terminal status', async () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-10-13T00:00:10.000Z'))
      const startedAt = Date.now() - 4000
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, opt_status: 'pending', opt_started_at_ms: startedAt, opt_last_sync_at_ms: startedAt }]
      vi.mocked(workspaceApi.listUnits).mockResolvedValueOnce({ items: [{
        ...baseUnit, opt_status: 'running', opt_elapsed_time: 3,
      }], total: 1 })

      await store.fetchUnits('ws-1')
      expect(store.units[0].opt_status).toBe('running')
      expect(store.units[0].opt_started_at_ms).toBe(startedAt)
      expect(store.units[0].opt_last_sync_at_ms).toBe(startedAt)

      vi.mocked(workspaceApi.listUnits).mockResolvedValueOnce({ items: [{
        ...baseUnit, opt_status: 'completed', opt_total: 10, opt_completed: 10,
        opt_remaining_time: 9,
      }], total: 1 })
      await store.fetchUnits('ws-1')
      expect(store.units[0]).toMatchObject({ opt_status: 'completed', opt_total: 10, opt_completed: 10 })
      expect(store.units[0].opt_started_at_ms).toBeNull()
      expect(store.units[0].opt_remaining_time).toBe(9)
    })
  })

  describe('unit mutation and selection boundaries', () => {
    it('rejects mutations for an inactive workspace and ignores inactive reads and run requests', async () => {
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-a')

      await store.fetchUnits('ws-b')
      expect(workspaceApi.listUnits).not.toHaveBeenCalled()
      await expect(store.createUnit('ws-b', {} as never)).rejects.toThrow('inactive workspace')
      await expect(store.batchCreateUnits('ws-b', [] as never)).rejects.toThrow('inactive workspace')
      await expect(store.updateUnit('ws-b', 'u-1', {} as never)).rejects.toThrow('inactive workspace')
      await expect(store.patchUnits('ws-b', ['u-1'], {} as never)).rejects.toThrow('inactive workspace')
      await expect(store.deleteUnit('ws-b', 'u-1')).rejects.toThrow('inactive workspace')
      await expect(store.bulkDeleteUnits('ws-b', ['u-1'])).rejects.toThrow('inactive workspace')
      await expect(store.reorderUnits('ws-b', [])).rejects.toThrow('inactive workspace')
      await expect(store.renameGroup('ws-b', {} as never)).rejects.toThrow('inactive workspace')
      await expect(store.renameUnit('ws-b', {} as never)).rejects.toThrow('inactive workspace')
      await store.runSelectedUnits('ws-b')

      expect(workspaceApi.createUnit).not.toHaveBeenCalled()
      expect(workspaceApi.batchCreateUnits).not.toHaveBeenCalled()
      expect(workspaceApi.updateUnit).not.toHaveBeenCalled()
      expect(workspaceApi.deleteUnit).not.toHaveBeenCalled()
      expect(workspaceApi.runUnits).not.toHaveBeenCalled()
    })

    it('filters duplicate and stale selections, applies returned run results, and starts polling', async () => {
      vi.useFakeTimers()
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit }, { ...baseUnit, id: 'u-2' }]
      store.setSelectedUnitIds(['u-1', 'missing', 'u-1', 'u-2'])
      expect(store.selectedUnitIds).toEqual(['u-1', 'u-2'])
      vi.mocked(workspaceApi.runUnits).mockResolvedValueOnce({ results: [
        { unit_id: 'u-1', status: 'running', task_id: 'task-1' },
        { unit_id: 'missing', status: 'failed', error: 'not present' },
        { unit_id: 'u-2', status: 'queued' },
      ] } as never)
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([{
        id: 'u-1', run_status: 'running', last_task_id: 'task-1', run_progress: 10,
      }] as never)

      const results = await store.runSelectedUnits('ws-1', true)

      expect(workspaceApi.runUnits).toHaveBeenCalledWith('ws-1', ['u-1', 'u-2'], true)
      expect(results).toHaveLength(3)
      expect(store.units[0]).toMatchObject({ run_status: 'running', last_task_id: 'task-1', run_progress: 10 })
      expect(store.units[1]).toMatchObject({ run_status: 'queued', run_progress: 0 })
      expect(store.running).toBe(false)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledWith('ws-1')
      store.stopPolling()
    })

    it('does not submit empty selections and restores running state when submission fails', async () => {
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit }]
      await store.runSelectedUnits('ws-1')
      expect(workspaceApi.runUnits).not.toHaveBeenCalled()

      store.setSelectedUnitIds(['u-1'])
      vi.mocked(workspaceApi.runUnits).mockRejectedValueOnce(new Error('queue unavailable'))
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([] as never)
      await expect(store.runSelectedUnits('ws-1')).rejects.toThrow('queue unavailable')
      expect(store.running).toBe(false)
      expect(store.units[0]).toMatchObject({ run_status: 'queued', run_progress: 0 })
      store.stopPolling()
    })

    it('does not apply a late mutation to a workspace activated while its request is pending', async () => {
      const pending = deferred<StrategyUnit>()
      vi.mocked(workspaceApi.createUnit).mockReturnValueOnce(pending.promise as never)
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-a')
      const request = store.createUnit('ws-a', { strategy_id: 's-a' } as never)
      store.activateWorkspace('ws-b')
      pending.resolve({ ...baseUnit, id: 'unit-a', workspace_id: 'ws-a' })
      const result = await request

      expect(workspaceApi.createUnit).toHaveBeenCalledWith('ws-a', { strategy_id: 's-a' })
      expect(result.id).toBe('unit-a')
      expect(store.activeWorkspaceId).toBe('ws-b')
      expect(store.units).toEqual([])
    })

    it('updates only returned units, removes deleted selections, and reorders the current list', async () => {
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [
        { ...baseUnit, id: 'u-1', sort_order: 0 },
        { ...baseUnit, id: 'u-2', sort_order: 1 },
        { ...baseUnit, id: 'u-3', sort_order: 2 },
      ]
      store.setSelectedUnitIds(['u-1', 'u-2', 'u-3'])
      vi.mocked(workspaceApi.updateUnit).mockImplementation(async (_workspaceId, unitId) => (
        { ...baseUnit, id: unitId, strategy_name: `updated ${unitId}` }
      ) as never)
      const patched = await store.patchUnits('ws-1', ['u-1', 'u-3'], { strategy_name: 'updated' } as never)
      expect(patched.map(unit => unit.id)).toEqual(['u-1', 'u-3'])
      expect(store.units.map(unit => unit.strategy_name)).toEqual(['updated u-1', 'sample', 'updated u-3'])
      expect(workspaceApi.updateUnit).toHaveBeenCalledTimes(2)

      vi.mocked(workspaceApi.bulkDeleteUnits).mockResolvedValueOnce({ deleted: 2 } as never)
      expect(await store.bulkDeleteUnits('ws-1', ['u-1', 'u-3'])).toBe(2)
      expect(workspaceApi.bulkDeleteUnits).toHaveBeenCalledWith('ws-1', { ids: ['u-1', 'u-3'] })
      expect(store.units.map(unit => unit.id)).toEqual(['u-2'])
      expect(store.selectedUnitIds).toEqual(['u-2'])

      store.units = [{ ...baseUnit, id: 'u-2' }, { ...baseUnit, id: 'u-4' }]
      vi.mocked(workspaceApi.reorderUnits).mockResolvedValueOnce(undefined as never)
      await store.reorderUnits('ws-1', ['u-4', 'u-2'])
      expect(workspaceApi.reorderUnits).toHaveBeenCalledWith('ws-1', { unit_ids: ['u-4', 'u-2'] })
      expect(store.units.map(unit => unit.id)).toEqual(['u-4', 'u-2'])
    })

    it('does not poll or stop when no valid unit is selected, and refreshes after stopping selected units', async () => {
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit }]
      store.setSelectedUnitIds(['missing'])
      await store.stopSelectedUnits('ws-1')
      expect(workspaceApi.stopUnits).not.toHaveBeenCalled()
      expect(workspaceApi.listUnits).not.toHaveBeenCalled()

      store.setSelectedUnitIds(['u-1'])
      vi.mocked(workspaceApi.stopUnits).mockResolvedValueOnce(undefined as never)
      vi.mocked(workspaceApi.listUnits).mockResolvedValueOnce({ items: [], total: 0 })
      await store.stopSelectedUnits('ws-1')
      expect(workspaceApi.stopUnits).toHaveBeenCalledWith('ws-1', ['u-1'])
      expect(workspaceApi.listUnits).toHaveBeenCalledWith('ws-1')
      expect(store.units).toEqual([])
    })
  })

  describe('status and polling recovery', () => {
    it.each(['queued', 'running'] as const)('continues polling while a unit is %s', async runStatus => {
      vi.useFakeTimers()
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, run_status: runStatus }]
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([{
        id: 'u-1', run_status: runStatus,
      }] as never)

      store.startPolling('ws-1', 3000)
      await vi.advanceTimersByTimeAsync(0)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(3000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(2)
      store.stopPolling()
    })

    it.each(['starting', 'running', 'live', 'connected'] as const)(
      'continues polling for a trading instance in %s state', async instanceStatus => {
        vi.useFakeTimers()
        const store = useWorkspaceStore()
        store.activateWorkspace('ws-1')
        const snapshot = { instance_status: instanceStatus } as never
        store.units = [{ ...baseUnit, run_status: 'idle', trading_snapshot: snapshot }]
        vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValue([{
          id: 'u-1', run_status: 'idle', trading_snapshot: snapshot,
        }] as never)

        store.startPolling('ws-1', 3000)
        await vi.advanceTimersByTimeAsync(0)
        expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)
        await vi.advanceTimersByTimeAsync(3000)
        expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(2)
        store.stopPolling()
      },
    )

    it('returns false for inactive, overlapping, stale, and failed status requests', async () => {
      const store = useWorkspaceStore()
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValueOnce([] as never)
      expect(await store.pollStatus('ws-a')).toBe(true)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledWith('ws-a')

      const first = deferred<any[]>()
      vi.mocked(workspaceApi.getUnitsStatus).mockReturnValueOnce(first.promise as never)
      const activeRequest = store.pollStatus('ws-a')
      expect(await store.pollStatus('ws-a')).toBe(false)
      store.activateWorkspace('ws-b')
      first.resolve([{ id: 'u-a', run_status: 'failed' }])
      expect(await activeRequest).toBe(false)

      vi.mocked(workspaceApi.getUnitsStatus).mockRejectedValueOnce(new Error('status service offline'))
      expect(await store.pollStatus('ws-b')).toBe(false)
      expect(store.activeWorkspaceId).toBe('ws-b')
    })

    it('applies non-optimization status fields and preserves an incomplete premature completion', async () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-10-13T00:00:10.000Z'))
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{
        ...baseUnit, id: 'u-1', run_status: 'running', opt_status: 'running', opt_total: 12,
        opt_completed: 3, opt_progress: 25, opt_started_at_ms: Date.now() - 2000,
      }]
      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValueOnce([{
        id: 'u-1', run_status: 'completed', last_task_id: 'task-finished', error_message: null,
        metrics_snapshot: { sharpe: 1.2 }, run_progress: 100, run_message: 'done', run_count: 4,
        last_run_time: '2026-10-12T00:00:00Z', bar_count: 200, trading_instance_id: 'instance-1',
        trading_snapshot: null, trading_mode: 'paper', lock_trading: false, lock_running: false,
        opt_status: 'completed', opt_total: 12, opt_completed: 4, opt_progress: 33,
        opt_elapsed_time: 2, opt_remaining_time: 8,
      }] as never)

      expect(await store.pollStatus('ws-1')).toBe(true)
      expect(store.units[0]).toMatchObject({
        run_status: 'completed', last_task_id: 'task-finished', metrics_snapshot: { sharpe: 1.2 },
        run_progress: 100, run_message: 'done', run_count: 4, bar_count: 200,
        trading_instance_id: 'instance-1', opt_status: 'running', opt_total: 12,
        opt_completed: 3, opt_progress: 25,
      })

      vi.mocked(workspaceApi.getUnitsStatus).mockResolvedValueOnce([{
        id: 'u-1', run_status: 'completed', opt_status: 'running', opt_total: 12,
        opt_completed: 6, opt_progress: 50, opt_elapsed_time: 7, opt_remaining_time: 5,
      }] as never)
      expect(await store.pollStatus('ws-1')).toBe(true)
      expect(store.units[0].opt_completed).toBe(6)
      expect(store.units[0].opt_started_at_ms).toBe(Date.now() - 7000)
      expect(store.units[0].opt_last_sync_at_ms).toBe(Date.now())
    })

    it('reconciles a queued optimization clock, lets stale running data age out, and clears null status timing', async () => {
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2026-10-13T00:00:10.000Z'))
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, opt_status: 'queued', opt_started_at_ms: Date.now() - 500 }]
      vi.mocked(workspaceApi.getUnitsStatus)
        .mockResolvedValueOnce([{ id: 'u-1', opt_status: null, opt_total: null, opt_completed: null }] as never)
        .mockResolvedValueOnce([{ id: 'u-1', opt_status: null, opt_total: 0, opt_completed: 0 }] as never)

      expect(await store.pollStatus('ws-1')).toBe(true)
      expect(store.units[0].opt_status).toBe('queued')
      expect(store.units[0].opt_started_at_ms).toBe(Date.now())
      expect(store.units[0].opt_elapsed_time).toBe(0)
      expect(store.units[0].opt_remaining_time).toBe(0)

      store.units[0].opt_status = 'running'
      store.units[0].opt_started_at_ms = Date.now() - 20_000
      store.units[0].opt_last_sync_at_ms = Date.now() - 20_000
      await store.pollStatus('ws-1')
      expect(store.units[0].opt_status).toBeNull()
      expect(store.units[0].opt_started_at_ms).toBeNull()
      expect(store.units[0].opt_last_sync_at_ms).toBeNull()
    })

    it('backs off repeated poll failures and stops after the configured retry limit', async () => {
      vi.useFakeTimers()
      const store = useWorkspaceStore()
      store.activateWorkspace('ws-1')
      store.units = [{ ...baseUnit, run_status: 'running' }]
      vi.mocked(workspaceApi.getUnitsStatus).mockRejectedValue(new Error('temporary disconnect'))

      store.startPolling('ws-1', 1000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1999)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(3999)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(1)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(3)
      await vi.advanceTimersByTimeAsync(30000)
      expect(workspaceApi.getUnitsStatus).toHaveBeenCalledTimes(3)
      store.stopPolling()
    })
  })
})
