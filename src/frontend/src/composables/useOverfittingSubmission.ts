import { ref } from 'vue'

import { strategyApi, type StrategyOverfittingMethod } from '@/api/strategy'

interface OverfittingRuntime {
  startRuntime: (taskId: string) => void
  stopRuntime: () => void
}

const DEFAULT_METHODS: StrategyOverfittingMethod[] = [
  'walk_forward',
  'out_of_sample',
  'monte_carlo',
]

export function useOverfittingSubmission(runtime: OverfittingRuntime) {
  const loading = ref(false)
  let generation = 0
  let unmounted = false

  async function submit(
    backtestId: string,
    methods: StrategyOverfittingMethod[] = DEFAULT_METHODS,
  ) {
    if (loading.value || unmounted) return
    const requestGeneration = ++generation
    let started = false
    runtime.stopRuntime()
    loading.value = true
    try {
      const submission = await strategyApi.createOverfittingTask(backtestId, {
        methods,
        walk_forward_train_days: 180,
        walk_forward_test_days: 60,
        walk_forward_step_days: 60,
        walk_forward_max_concurrency: 4,
        out_of_sample_ratio: 0.3,
        monte_carlo_iterations: 300,
      })
      if (unmounted || requestGeneration !== generation) return
      runtime.startRuntime(submission.task_id)
      started = true
    } catch {
      if (unmounted || requestGeneration !== generation) return
      runtime.stopRuntime()
    } finally {
      if (requestGeneration === generation && !started) loading.value = false
    }
  }

  function invalidate() {
    generation++
    runtime.stopRuntime()
  }

  function dispose() {
    unmounted = true
    invalidate()
  }

  return { loading, submit, invalidate, dispose }
}
