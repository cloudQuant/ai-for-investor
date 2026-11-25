import { inject, type InjectionKey } from 'vue'
import type { useStrategyPage } from './useStrategyPage'

export type StrategyPageContext = ReturnType<typeof useStrategyPage>

export const STRATEGY_PAGE_KEY: InjectionKey<StrategyPageContext> = Symbol('StrategyPageContext')

export function useStrategyPageContext(): StrategyPageContext {
  const context = inject(STRATEGY_PAGE_KEY)
  if (!context) {
    throw new Error('StrategyPageContext is missing')
  }
  return context
}
