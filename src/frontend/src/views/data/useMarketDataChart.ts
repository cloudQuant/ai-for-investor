import type { ComputedRef, Ref } from 'vue'
import * as echarts from 'echarts'
import type { MarketHistoryRow } from '@/api/marketData'
import { CANDLE_DOWN_COLOR, CANDLE_ITEM_STYLE, CANDLE_UP_COLOR } from '@/constants/chartColors'
import {
  candleColor,
  cumulativeReturns,
  drawdownSeries,
  formatNumber,
  isFiniteNumber,
  numericValue,
  ohlcTuple,
} from './marketDataFormatters'
import type {
  ChartMode,
  DataPageDisplayMode,
  MarketChartOptionDraft,
  OpenDataDirectKlineDisplayState,
} from './marketDataTypes'

export interface MarketDataChartDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  dataPageDisplayMode: Ref<DataPageDisplayMode>
  openDataDirectKlineDisplay: Ref<OpenDataDirectKlineDisplayState>
  chartCanRender: ComputedRef<boolean>
  chartMode: Ref<ChartMode>
  marketChartRef: Ref<HTMLDivElement | undefined>
  historyRows: ComputedRef<MarketHistoryRow[]>
  ohlcHistoryRows: ComputedRef<MarketHistoryRow[]>
  hasOhlcChart: ComputedRef<boolean>
  viewportWidth: Ref<number>
}

export function createMarketDataChartManager(deps: MarketDataChartDeps) {
  let marketChart: echarts.ECharts | null = null
  let marketChartElement: HTMLDivElement | null = null

  function themeColor(name: string, fallback: string) {
    if (typeof window === 'undefined') return fallback
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return value || fallback
  }

  function chartPalette() {
    return {
      primary: themeColor('--primary-color', 'royalblue'),
      danger: themeColor('--danger-color', 'crimson'),
      success: themeColor('--success-color', 'seagreen'),
      warning: themeColor('--warning-color', 'goldenrod'),
      info: themeColor('--info-text-color', 'slateblue'),
      secondary: themeColor('--text-color-secondary', 'slategray'),
      mutedText: themeColor('--text-color-regular', 'dimgray'),
      border: themeColor('--border-color', 'lightgray'),
      grid: themeColor('--border-color-light', 'gainsboro'),
    }
  }

  function compactAxisLabel(value: unknown) {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return String(value ?? '')
    const absValue = Math.abs(numeric)
    if (absValue >= 1e8) return deps.t('dataMgmt.compactHundredMillion', { value: (numeric / 1e8).toFixed(1) })
    if (absValue >= 1e4) return deps.t('dataMgmt.compactTenThousand', { value: (numeric / 1e4).toFixed(1) })
    return String(numeric)
  }

  function baseChartOption(option: MarketChartOptionDraft): echarts.EChartsOption {
    const { legend, ...restOption } = option
    const palette = chartPalette()
    return {
      animation: false,
      color: [palette.primary, palette.danger, palette.success, palette.warning, palette.info],
      backgroundColor: 'transparent',
      legend: {
        top: 8,
        left: 56,
        itemWidth: 10,
        itemHeight: 8,
        textStyle: { color: palette.mutedText, fontSize: 12 },
        data: legend,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        valueFormatter: (value: unknown) => (typeof value === 'number' ? formatNumber(value) : String(value ?? '-')),
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      ...restOption,
    }
  }

  function categoryAxis(data: string[]): echarts.XAXisComponentOption {
    const palette = chartPalette()
    return {
      type: 'category',
      data,
      boundaryGap: false,
      axisLine: { lineStyle: { color: palette.border }, onZero: false },
      axisTick: { show: false },
      axisLabel: { color: palette.secondary, hideOverlap: true },
      splitLine: { show: false },
    }
  }

  function valueAxis(overrides: Partial<echarts.YAXisComponentOption> = {}): echarts.YAXisComponentOption {
    const palette = chartPalette()
    return {
      type: 'value',
      scale: true,
      axisLabel: { color: palette.secondary, formatter: compactAxisLabel },
      splitLine: { lineStyle: { color: palette.grid, type: 'dashed' } },
      ...overrides,
    } as echarts.YAXisComponentOption
  }

  function dataZoom(xAxisIndex: number[]): echarts.DataZoomComponentOption[] {
    return [
      { type: 'inside', xAxisIndex, start: 55, end: 100 },
      { type: 'slider', xAxisIndex, height: 18, bottom: 16, start: 55, end: 100 },
    ]
  }

  function movingAverage(data: number[][], period: number) {
    return data.map((_, index) => {
      if (index < period - 1) return '-'
      const slice = data.slice(index - period + 1, index + 1)
      const average = slice.reduce((sum, item) => sum + item[1], 0) / period
      return Number(average.toFixed(4))
    })
  }

  function movingAverageSeries(name: string, data: number[][], period: number): echarts.SeriesOption {
    return {
      name,
      type: 'line',
      data: movingAverage(data, period),
      smooth: true,
      showSymbol: false,
      lineStyle: { width: 1.5, opacity: 0.75 },
    }
  }

  function buildOpenDataDirectKlineChartOption(): echarts.EChartsOption {
    const rows = deps.openDataDirectKlineDisplay.value.rows
    const dates = rows.map((row) => row.date)
    const ohlc = rows.map((row) => [row.open, row.close, row.low, row.high])
    const volumeBars = rows.map((row) => ({
      value: row.volume,
      itemStyle: { color: row.close >= row.open ? CANDLE_UP_COLOR : CANDLE_DOWN_COLOR },
    }))

    return baseChartOption({
      legend: [deps.t('charts.klineSeries'), deps.t('charts.klineVolume')],
      grid: [
        { left: 64, right: 28, top: 42, height: '55%' },
        { left: 64, right: 28, top: '73%', height: '16%' },
      ],
      xAxis: [
        categoryAxis(dates),
        { ...categoryAxis(dates), gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        valueAxis(),
        valueAxis({ gridIndex: 1, splitNumber: 2, axisLabel: { show: false } }),
      ],
      dataZoom: dataZoom([0, 1]),
      series: [
        {
          name: deps.t('charts.klineSeries'),
          type: 'candlestick',
          data: ohlc,
          itemStyle: CANDLE_ITEM_STYLE,
        },
        {
          name: deps.t('charts.klineVolume'),
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeBars,
          barMaxWidth: 12,
        },
      ],
    })
  }

  function buildPriceChartOption(): echarts.EChartsOption {
    const rows = deps.ohlcHistoryRows.value
    const dates = rows.map((row) => String(row.date))
    const ohlc = rows.map((row) => ohlcTuple(row))
    const volumeBars = rows.map((row) => ({
      value: numericValue(row.volume, 0),
      itemStyle: { color: candleColor(row) },
    }))

    return baseChartOption({
      legend: [deps.t('charts.klineSeries'), 'MA5', 'MA20', deps.t('charts.klineVolume')],
      grid: [
        { left: 64, right: 28, top: 42, height: '55%' },
        { left: 64, right: 28, top: '73%', height: '16%' },
      ],
      xAxis: [
        categoryAxis(dates),
        { ...categoryAxis(dates), gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        valueAxis(),
        valueAxis({ gridIndex: 1, splitNumber: 2, axisLabel: { show: false } }),
      ],
      dataZoom: dataZoom([0, 1]),
      series: [
        {
          name: deps.t('charts.klineSeries'),
          type: 'candlestick',
          data: ohlc,
          itemStyle: CANDLE_ITEM_STYLE,
        },
        movingAverageSeries('MA5', ohlc, 5),
        movingAverageSeries('MA20', ohlc, 20),
        {
          name: deps.t('charts.klineVolume'),
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumeBars,
          barMaxWidth: 12,
        },
      ],
    })
  }

  function buildReturnChartOption(): echarts.EChartsOption {
    const rows = deps.ohlcHistoryRows.value
    const dates = rows.map((row) => String(row.date))
    const closes = rows.map((row) => numericValue(row.close, null)).filter(isFiniteNumber)
    const returns = cumulativeReturns(closes)
    const drawdowns = drawdownSeries(closes)
    const volumes = rows.map((row) => numericValue(row.volume, 0))
    const palette = chartPalette()

    return baseChartOption({
      legend: [
        deps.t('dataMgmt.chartCumulativeReturn'),
        deps.t('dataMgmt.chartDrawdown'),
        deps.t('charts.klineVolume'),
      ],
      grid: [
        { left: 64, right: 28, top: 42, height: '55%' },
        { left: 64, right: 28, top: '73%', height: '16%' },
      ],
      xAxis: [
        categoryAxis(dates),
        { ...categoryAxis(dates), gridIndex: 1, axisLabel: { show: false } },
      ],
      yAxis: [
        valueAxis({ axisLabel: { formatter: '{value}%' } }),
        valueAxis({ gridIndex: 1, splitNumber: 2, axisLabel: { show: false } }),
      ],
      dataZoom: dataZoom([0, 1]),
      series: [
        {
          name: deps.t('dataMgmt.chartCumulativeReturn'),
          type: 'line',
          data: returns,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 2, color: palette.primary },
          areaStyle: { opacity: 0.16 },
        },
        {
          name: deps.t('dataMgmt.chartDrawdown'),
          type: 'line',
          data: drawdowns,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1.6, color: palette.danger },
        },
        {
          name: deps.t('charts.klineVolume'),
          type: 'bar',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: volumes,
          itemStyle: { color: palette.secondary },
          barMaxWidth: 12,
        },
      ],
    })
  }

  function buildLiquidityChartOption(): echarts.EChartsOption {
    const rows = deps.ohlcHistoryRows.value.length ? deps.ohlcHistoryRows.value : deps.historyRows.value
    const dates = rows.map((row, index) => String(row.date || row.name || index + 1))
    const volume = rows.map((row) => numericValue(row.volume, 0))
    const turnover = rows.map((row) => numericValue(row.turnover, null))
    const openInterest = rows.map((row) => numericValue(row.open_interest, null))
    const palette = chartPalette()

    return baseChartOption({
      legend: [
        deps.t('charts.klineVolume'),
        deps.t('dataMgmt.fieldTurnover'),
        deps.t('dataMgmt.fieldOpenInterest'),
      ],
      grid: [{ left: 64, right: 36, top: 44, bottom: 54 }],
      xAxis: [categoryAxis(dates)],
      yAxis: [
        valueAxis(),
        valueAxis({ axisLabel: { formatter: compactAxisLabel }, splitLine: { show: false } }),
      ],
      dataZoom: dataZoom([0]),
      series: [
        {
          name: deps.t('charts.klineVolume'),
          type: 'bar',
          data: volume,
          itemStyle: { color: palette.success },
          barMaxWidth: 14,
        },
        {
          name: deps.t('dataMgmt.fieldTurnover'),
          type: 'line',
          yAxisIndex: 1,
          data: turnover,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: palette.warning, width: 2 },
        },
        {
          name: deps.t('dataMgmt.fieldOpenInterest'),
          type: 'line',
          yAxisIndex: 1,
          data: openInterest,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: palette.info, width: 2 },
        },
      ],
    })
  }

  function buildStructureChartOption(): echarts.EChartsOption {
    const rows = deps.historyRows.value
    const labels = rows.map((row, index) => String(row.name || row.date || index + 1))
    const palette = chartPalette()

    return baseChartOption({
      legend: [
        deps.t('charts.klineVolume'),
        deps.t('dataMgmt.fieldOpenInterest'),
        deps.t('dataMgmt.colChangeValue'),
      ],
      grid: [{ left: 64, right: 36, top: 44, bottom: 58 }],
      xAxis: [categoryAxis(labels)],
      yAxis: [
        valueAxis(),
        valueAxis({ splitLine: { show: false } }),
      ],
      dataZoom: labels.length > 8 ? dataZoom([0]) : [],
      series: [
        {
          name: deps.t('charts.klineVolume'),
          type: 'bar',
          data: rows.map((row) => numericValue(row.volume, 0)),
          itemStyle: { color: palette.primary },
          barMaxWidth: 18,
        },
        {
          name: deps.t('dataMgmt.fieldOpenInterest'),
          type: 'bar',
          data: rows.map((row) => numericValue(row.open_interest, 0)),
          itemStyle: { color: palette.info },
          barMaxWidth: 18,
        },
        {
          name: deps.t('dataMgmt.colChangeValue'),
          type: 'line',
          yAxisIndex: 1,
          data: rows.map((row) => numericValue(row.change, null)),
          smooth: true,
          lineStyle: { color: palette.danger, width: 2 },
        },
      ],
    })
  }

  function buildMarketChartOption(): echarts.EChartsOption {
    if (!deps.hasOhlcChart.value || deps.chartMode.value === 'structure') {
      return buildStructureChartOption()
    }
    if (deps.chartMode.value === 'return') {
      return buildReturnChartOption()
    }
    if (deps.chartMode.value === 'liquidity') {
      return buildLiquidityChartOption()
    }
    return buildPriceChartOption()
  }

  function renderMarketChart() {
    const isDirectDisplay = deps.dataPageDisplayMode.value === 'opendata_direct'
    const canRender = isDirectDisplay
      ? deps.openDataDirectKlineDisplay.value.status === 'ready'
        && deps.openDataDirectKlineDisplay.value.rows.length > 0
      : deps.chartCanRender.value
    if (!canRender || !deps.marketChartRef.value) {
      disposeMarketChart()
      return
    }
    if (marketChart && marketChartElement !== deps.marketChartRef.value) {
      disposeMarketChart()
    }
    if (!marketChart) {
      marketChart = echarts.init(deps.marketChartRef.value)
      marketChartElement = deps.marketChartRef.value
    }
    marketChart.setOption(
      isDirectDisplay ? buildOpenDataDirectKlineChartOption() : buildMarketChartOption(),
      true,
    )
    marketChart.resize()
  }

  function resizeMarketChart() {
    marketChart?.resize()
  }

  function handleViewportResize() {
    deps.viewportWidth.value = window.innerWidth
    resizeMarketChart()
  }

  function disposeMarketChart() {
    marketChart?.dispose()
    marketChart = null
    marketChartElement = null
  }

  return {
    getMarketChart: () => marketChart,
    renderMarketChart,
    resizeMarketChart,
    handleViewportResize,
    disposeMarketChart,
    buildOpenDataDirectKlineChartOption,
    buildMarketChartOption,
    buildPriceChartOption,
    buildReturnChartOption,
    buildLiquidityChartOption,
    buildStructureChartOption,
    baseChartOption,
    categoryAxis,
    valueAxis,
    themeColor,
    chartPalette,
    dataZoom,
    movingAverageSeries,
    movingAverage,
    compactAxisLabel,
  }
}
