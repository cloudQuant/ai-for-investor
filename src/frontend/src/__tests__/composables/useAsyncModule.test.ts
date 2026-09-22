import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useAsyncModule } from '@/composables/useAsyncModule'

function mountModuleLoader<T>(
  loadModule: () => Promise<T>,
  options: { timeoutMs?: number } = {},
) {
  let resource!: ReturnType<typeof useAsyncModule<T>>
  const wrapper = mount(defineComponent({
    setup() {
      resource = useAsyncModule(loadModule, options)
      return () => h('div')
    },
  }))
  return { wrapper, resource }
}

describe('useAsyncModule', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('exposes a rejected dynamic module load and retries successfully', async () => {
    const module = { marker: 'loaded' }
    const loadModule = vi.fn<() => Promise<typeof module>>()
      .mockRejectedValueOnce(new Error('chunk request failed'))
      .mockResolvedValueOnce(module)
    const { wrapper, resource } = mountModuleLoader(loadModule)

    await resource.load()
    expect(resource.error.value).toBe('failed')
    expect(resource.loading.value).toBe(false)

    await resource.retry()
    expect(resource.value.value).toBe(module)
    expect(resource.error.value).toBe(null)
    expect(loadModule).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  it('reports a visible timeout state for a stalled module load', async () => {
    vi.useFakeTimers()
    const { wrapper, resource } = mountModuleLoader(
      () => new Promise(() => {}),
      { timeoutMs: 50 },
    )

    const pendingLoad = resource.load()
    await vi.advanceTimersByTimeAsync(50)
    await pendingLoad

    expect(resource.error.value).toBe('timeout')
    expect(resource.loading.value).toBe(false)
    wrapper.unmount()
  })

  it('does not apply a module that resolves after the owner unmounts', async () => {
    let resolveModule!: (value: { marker: string }) => void
    const { wrapper, resource } = mountModuleLoader(
      () => new Promise(resolve => { resolveModule = resolve }),
    )

    const pendingLoad = resource.load()
    wrapper.unmount()
    resolveModule({ marker: 'too late' })
    await pendingLoad

    expect(resource.value.value).toBe(null)
    expect(resource.error.value).toBe(null)
  })
})
