import type { OptimizationDirection, OptimizationObjective } from '@/types/workspace'

export interface OptimizationTarget {
  objective: OptimizationObjective
  direction: OptimizationDirection
}

const DEFAULT_DIRECTION: Record<OptimizationObjective, OptimizationDirection> = {
  sharpe_ratio: 'maximize',
  total_return: 'maximize',
  max_drawdown: 'minimize',
}

const LEGACY_TARGETS: Record<string, OptimizationTarget> = {
  sharpe_max: { objective: 'sharpe_ratio', direction: 'maximize' },
  max_return: { objective: 'total_return', direction: 'maximize' },
  min_drawdown: { objective: 'max_drawdown', direction: 'minimize' },
}

export function isOptimizationObjective(value: unknown): value is OptimizationObjective {
  return value === 'sharpe_ratio' || value === 'total_return' || value === 'max_drawdown'
}

export function isOptimizationDirection(value: unknown): value is OptimizationDirection {
  return value === 'maximize' || value === 'minimize'
}

export function defaultOptimizationDirection(
  objective: OptimizationObjective,
): OptimizationDirection {
  return DEFAULT_DIRECTION[objective]
}

export function resolveOptimizationTarget(
  objective: unknown,
  direction?: unknown,
): OptimizationTarget {
  const legacyTarget = typeof objective === 'string' ? LEGACY_TARGETS[objective] : undefined
  const resolvedObjective = isOptimizationObjective(objective)
    ? objective
    : legacyTarget?.objective ?? 'sharpe_ratio'

  return {
    objective: resolvedObjective,
    direction: isOptimizationDirection(direction)
      ? direction
      : legacyTarget?.direction ?? DEFAULT_DIRECTION[resolvedObjective],
  }
}
