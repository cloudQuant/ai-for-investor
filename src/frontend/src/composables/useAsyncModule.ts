import { onUnmounted, ref, shallowRef } from 'vue'

export type AsyncModuleLoadError = 'failed' | 'timeout'

export interface UseAsyncModuleOptions {
  timeoutMs?: number
}

/** Load a lazy module with retryable state and ignore results after unmount. */
export function useAsyncModule<T>(
  loadModule: () => Promise<T>,
  options: UseAsyncModuleOptions = {},
) {
  const value = shallowRef<T | null>(null)
  const loading = ref(false)
  const error = ref<AsyncModuleLoadError | null>(null)
  const timeoutMs = options.timeoutMs
  let requestId = 0
  let disposed = false
  let timeoutHandle: ReturnType<typeof setTimeout> | null = null

  onUnmounted(() => {
    disposed = true
    requestId += 1
    if (timeoutHandle !== null) clearTimeout(timeoutHandle)
    timeoutHandle = null
  })

  async function load(): Promise<void> {
    if (disposed || loading.value || value.value !== null) return

    const currentRequestId = ++requestId
    let timedOut = false
    loading.value = true
    error.value = null

    try {
      const modulePromise = loadModule()
      const loadedModule = timeoutMs && timeoutMs > 0
        ? await Promise.race([
            modulePromise,
            new Promise<never>((_resolve, reject) => {
              timeoutHandle = setTimeout(() => {
                timedOut = true
                reject(new Error('Async module load timed out'))
              }, timeoutMs)
            }),
          ])
        : await modulePromise

      if (!disposed && currentRequestId === requestId) {
        value.value = loadedModule
      }
    } catch {
      if (!disposed && currentRequestId === requestId) {
        error.value = timedOut ? 'timeout' : 'failed'
      }
    } finally {
      if (timeoutHandle !== null) clearTimeout(timeoutHandle)
      timeoutHandle = null
      if (!disposed && currentRequestId === requestId) {
        loading.value = false
      }
    }
  }

  return { value, loading, error, load, retry: load }
}
