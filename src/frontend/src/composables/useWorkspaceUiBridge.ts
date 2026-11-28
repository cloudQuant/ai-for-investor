import { provideWorkspaceI18n } from '@bt-api/workspace-ui/core'
import { useI18n } from 'vue-i18n'

/**
 * Bridges ai-for-investor's vue-i18n instance into @bt-api/workspace-ui components
 * for both Trading and Research workspaces.
 */
export function useWorkspaceUiBridge(): void {
  const i18n = useI18n()
  const t = i18n.t

  const keyResolvers: Record<string, () => string> = {
    save: () => t('workspaceDialogs.save'),
    cancel: () => t('workspaceDialogs.cancel'),
    confirm: () => t('common.confirm'),
    tipSelectToggle: () => `${t('workspaceDialogs.selectAll')} / ${t('workspaceDialogs.deselectAll')}`,
    tipAutoEnable: () => t('workspaceDialogs.autoTradingEnable'),
    tipAutoDisable: () => t('workspaceDialogs.autoTradingDisable'),
    tipLockTrading: () => t('workspaceDialogs.lockTrading'),
    tipLockRunning: () => t('workspaceDialogs.lockRunning'),
    tipUnlock: () => t('workspaceDialogs.unlock'),
    tipStartSelected: () => t('workspaceDialogs.startUnits'),
    tipStopSelected: () => t('workspaceDialogs.stopUnits'),
    tipAddUnits: () => t('workspaceDialogs.newUnit'),
    tipRemoveUnits: () => t('workspaceDialogs.deleteUnits'),
    tipImportUnits: () => t('workspaceDialogs.importTitle'),
    tipExportUnits: () => t('workspaceDialogs.exportTitle'),
    tipDataSource: () => t('workspaceDialogs.dataSourceTitle'),
    tipUnitSettings: () => t('workspaceDialogs.unitSettingsTitle'),
    tipStrategyParams: () => t('workspaceDialogs.formulaApply'),
    tipPositionManager: () => t('workspaceDialogs.positionManager'),
    tipOpenChart: () => `${t('workspaceDialogs.open')} K`,
    tipOpenReport: () => t('workspaceDialogs.openPortfolioReport'),
    tipAutoConfig: () => t('workspaceDialogs.autoTradingConfig'),
    tipDailyStats: () => t('workspaceDialogs.tradingDayStat'),
    tipGroupLink: () => t('workspaceDialogs.groupLink'),
    tipRenameGroup: () => t('units.groupRename'),
    tipRenameUnit: () => t('units.renameUnit'),
    tipMoveUp: () => t('units.moveUp'),
    tipMoveDown: () => t('units.moveDown'),
    tipMoveTop: () => t('units.moveTop'),
    tipMoveBottom: () => t('units.moveBottom'),
    resRunSerial: () => t('units.runSerial'),
    resRunParallel: () => t('units.runParallel'),
    resStopSelected: () => t('units.stopSelected'),
    resReloadStrategy: () => t('units.reloadStrategy'),
    resCreateUnit: () => t('units.createUnit'),
    resDeleteUnit: () => t('units.deleteUnit'),
    resImportUnits: () => t('units.importUnits'),
    resExportUnits: () => t('units.exportUnits'),
    resSwitchSymbol: () => t('units.switchSymbol'),
    resViewResults: () => t('units.viewBacktestResults'),
    resParamOpt: () => t('units.paramOpt'),
    resThreadOpt: () => t('units.threadOpt'),
    resBatchParamOpt: () => t('units.batchParamOpt'),
    resSubmitBatchOpt: () => t('units.submitBatchOpt'),
    resCopyOptParams: () => t('units.paramOptCopy'),
    resOptResults: () => t('units.optResults'),
    resMultiTaskReport: () => t('units.multiTaskReport'),
    resChangeSymbolTitle: () => t('workspaceDialogs.csTitle'),
    resSymbolCode: () => t('workspaceDialogs.csSymbolCode'),
    resSymbolCodePlaceholder: () => t('workspaceDialogs.csSymbolCodeHint'),
    resSymbolName: () => t('workspaceDialogs.csSymbolName'),
    resSymbolNamePlaceholder: () => t('workspaceDialogs.csSymbolNameHint'),
    resTimeframe: () => t('workspaceDialogs.csTimeframe'),
    resApplyScope: () => t('workspaceDialogs.csApplyScope'),
    resScopeSingle: () => t('workspaceDialogs.csScopeSingle'),
    resScopeSelected: () => t('workspaceDialogs.csScopeSelected'),
    resThreadOptTitle: () => t('workspaceDialogs.otdTitle'),
    resParallelThreads: () => t('workspaceDialogs.otdParallelThreads'),
    resRunMode: () => t('workspaceDialogs.otdRunMode'),
    resModeGrid: () => t('workspaceDialogs.otdModeGrid'),
    resModeRandom: () => t('workspaceDialogs.otdModeRandom'),
    resTimeoutSec: () => t('workspaceDialogs.otdTimeoutSec'),
    resTimeoutZeroHint: () => t('workspaceDialogs.otdTimeoutZeroHint'),
    resScheduledOptTitle: () => t('workspaceDialogs.scheduledOptTitle'),
    resScheduledOpt: () => t('workspaceDialogs.scheduledOpt'),
    resCurrentStatus: () => t('workspaceDialogs.currentStatus'),
    resRunFreq: () => t('workspaceDialogs.runFreq'),
    resAutoTrigger: () => t('workspaceDialogs.autoTrigger'),
    resRunTime: () => t('workspaceDialogs.runTime'),
    resWorkspaceTimePoint: () => t('workspaceDialogs.workspaceTimePoint'),
    resSessionScope: () => t('workspaceDialogs.sessionScope'),
    resEnableScheduledOpt: () => t('workspaceDialogs.enabledScheduledOpt'),
    resFreqDaily: () => t('workspaceDialogs.freqDaily'),
    resFreqWeekly: () => t('workspaceDialogs.weekly'),
    resAllUnits: () => t('workspaceDialogs.allTradingUnits'),
    resSelectedUnits: () => t('workspaceDialogs.onlySelectedUnits'),
    resRunWhenIdle: () => t('workspaceDialogs.runWhenIdle'),
    metaEnabled: () => t('workspaceDialogs.enabledStatus'),
    metaDisabled: () => t('workspaceDialogs.disabledStatus'),
    metaSelected: () => t('workspaceDialogs.selectedSuffix'),
  }

  provideWorkspaceI18n({
    locale: () => {
      const maybeLocale = (i18n as { locale?: { value?: string } }).locale
      return maybeLocale?.value ? String(maybeLocale.value) : 'zh-CN'
    },
    t: (key, params) => {
      if (key === 'resTotalUnits' && params && 'count' in params) {
        return `${t('units.total')} ${params.count} ${t('units.nUnitsSuffix')}`
      }
      const resolver = keyResolvers[key]
      return resolver ? resolver() : undefined
    },
  })
}
