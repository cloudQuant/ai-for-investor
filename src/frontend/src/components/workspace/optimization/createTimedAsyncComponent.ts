import { defineAsyncComponent, type AsyncComponentLoader, type Component } from 'vue'

export function createTimedAsyncComponent(
  loader: AsyncComponentLoader,
  loadingComponent: Component,
  timeoutMs: number,
) {
  return defineAsyncComponent({
    loader,
    loadingComponent,
    delay: 0,
    timeout: timeoutMs,
    suspensible: false,
  })
}
