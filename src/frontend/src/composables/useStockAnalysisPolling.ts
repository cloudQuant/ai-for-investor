/** Sequential task-polling helper that prevents overlapping requests and post-unmount updates. */
export function useStockAnalysisPolling(intervalMs = 3000) {
  let pollingTimer: number | null = null
  let pollingGen = 0
  let unmounted = false

  function stopPolling(): void {
    if (pollingTimer !== null) {
      window.clearTimeout(pollingTimer)
      pollingTimer = null
    }
  }

  function invalidatePolling(): number {
    stopPolling()
    pollingGen += 1
    return pollingGen
  }

  function startPolling(taskId: string, onTick: (id: string, gen: number) => Promise<void>): void {
    const gen = invalidatePolling()
    const scheduleNext = () => {
      if (unmounted || gen !== pollingGen) return
      pollingTimer = window.setTimeout(() => {
        void onTick(taskId, gen).then(() => {
          if (!unmounted && gen === pollingGen && pollingTimer !== null) {
            scheduleNext()
          }
        })
      }, intervalMs)
    }
    scheduleNext()
  }

  function isCurrent(gen: number): boolean {
    return !unmounted && gen === pollingGen
  }

  function isUnmounted(): boolean {
    return unmounted
  }

  function dispose(): void {
    unmounted = true
    invalidatePolling()
  }

  return { startPolling, stopPolling, invalidatePolling, isCurrent, isUnmounted, dispose, currentGen: () => pollingGen }
}
