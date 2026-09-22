import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, type AsyncComponentLoader, type Component } from 'vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { createTimedAsyncComponent } from '@/components/workspace/optimization/createTimedAsyncComponent'
import { elStubs } from '@/test/stubs'

const loadingComponent = defineComponent({
  setup() {
    return () => h('div', { role: 'status', 'aria-live': 'polite' }, 'Loading optimization tab')
  },
})

const elResultStub = defineComponent({
  props: ['title', 'subTitle'],
  setup(props, { slots }) {
    return () => h('div', { class: 'el-result' }, [
      h('div', { class: 'el-result__title' }, props.title),
      slots.extra?.(),
    ])
  },
})

function mountTimedComponent(loader: AsyncComponentLoader, timeoutMs = 15_000) {
  const AsyncComponent = createTimedAsyncComponent(loader, loadingComponent, timeoutMs)
  return mount(ErrorBoundary, {
    slots: { default: () => h(AsyncComponent) },
    global: { stubs: { ...elStubs, 'el-result': elResultStub } },
  })
}

describe('createTimedAsyncComponent', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('shows loading, surfaces a rejected dynamic import, and retries through ErrorBoundary', async () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const loadedComponent: Component = defineComponent({
      setup() {
        return () => h('div', { class: 'loaded-component' }, 'Optimization loaded')
      },
    })
    let attempt = 0
    const loader: AsyncComponentLoader = vi.fn(() => {
      if (attempt++ === 0) return Promise.reject(new Error('dynamic import rejected'))
      return Promise.resolve(loadedComponent)
    })
    const wrapper = mountTimedComponent(loader)

    expect(wrapper.get('[role="status"]').text()).toBe('Loading optimization tab')
    await flushPromises()
    expect(wrapper.find('.error-boundary').exists()).toBe(true)
    expect(wrapper.find('.el-button').text()).toBe('重试')

    await wrapper.get('.error-boundary .el-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.loaded-component').exists()).toBe(true)
    expect(loader).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    expect(consoleError).toHaveBeenCalled()
  })

  it('shows a retryable error when the async component times out', async () => {
    vi.useFakeTimers()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const loader: AsyncComponentLoader = () => new Promise(() => {})
    const wrapper = mountTimedComponent(loader, 50)

    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(50)
    await flushPromises()

    expect(wrapper.find('.error-boundary').exists()).toBe(true)
    expect(wrapper.find('.el-button').text()).toBe('重试')
    wrapper.unmount()
    expect(consoleError).toHaveBeenCalled()
  })

  it('does not surface late component resolution after unmount', async () => {
    let resolveModule!: (module: Component) => void
    const loader: AsyncComponentLoader = () => new Promise<Component>(resolve => { resolveModule = resolve })
    const wrapper = mountTimedComponent(loader)

    expect(wrapper.find('[role="status"]').exists()).toBe(true)
    wrapper.unmount()
    resolveModule(defineComponent({ setup: () => () => h('div', 'late result') }))
    await flushPromises()

    expect(wrapper.find('.loaded-component').exists()).toBe(false)
  })
})
