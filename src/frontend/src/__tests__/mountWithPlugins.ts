/**
 * Shared mounting helper for view tests.
 * Provides isolated Pinia and Router instances for each mount.
 */
import type { Component, Directive } from 'vue'
import { mount, type ComponentMountingOptions, type MountingOptions } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { vi } from 'vitest'

import { elStubs } from './stubs'

type ComponentStubMap = Record<string, boolean | Component | Directive>

// Mock element-plus locale
vi.mock('element-plus/dist/locale/zh-cn.mjs', () => ({ default: {} }))

export type MountOptions<T extends Component = Component> = ComponentMountingOptions<T> & {
  customStubs?: ComponentStubMap
}

export function mountWithPlugins<T extends Component>(
  component: T,
  options: MountOptions<T> = {}
): ReturnType<typeof mount<T, T>> {
  const { customStubs, ...mountOptions } = options
  const pinia = createPinia()
  setActivePinia(pinia)
  const globalStubs = mountOptions.global?.stubs
  const globalStubMap: ComponentStubMap = Array.isArray(globalStubs)
    ? Object.fromEntries((globalStubs as string[]).map((name) => [name, true] as const))
    : globalStubs ?? {}
  const stubs: ComponentStubMap = {
    ...elStubs,
    ...customStubs,
    ...globalStubMap,
  }

  const plugins: NonNullable<MountingOptions<Component>['global']>['plugins'] = [pinia]
  if (!mountOptions.global?.mocks?.['$router']) {
    plugins.push(
      createRouter({
        history: createMemoryHistory(),
        routes: [
          { path: '/', component: { template: '<div></div>' } },
          { path: '/login', component: { template: '<div></div>' } },
          { path: '/register', component: { template: '<div></div>' } },
          { path: '/dashboard', component: { template: '<div></div>' } },
        ],
      }),
    )
  }

  return mount(component, {
    ...mountOptions,
    global: {
      ...mountOptions.global,
      plugins,
      stubs,
    },
  })
}
