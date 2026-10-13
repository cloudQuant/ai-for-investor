// @vitest-environment jsdom
// DOMPurify relies on real Node.prototype.nodeName semantics; happy-dom can remove allowed tags.
// Keep jsdom scoped to Markdown tests; other frontend tests remain in happy-dom.
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { elStubs } from '@/test/stubs'
import StockAnalysisPage from '@/views/investment/StockAnalysisPage.vue'

const mocks = vi.hoisted(() => ({
  createTask: vi.fn(),
  getTask: vi.fn(),
  getTaskResult: vi.fn(),
  getLatestResult: vi.fn(),
  getSignalHistory: vi.fn(),
  getSignalSummary: vi.fn(),
  cancelTask: vi.fn(),
  exportReport: vi.fn(),
  getMyAvailableModels: vi.fn(),
  messageSuccess: vi.fn(),
  messageWarning: vi.fn(),
  messageError: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
}))

vi.mock('@/api/stockAnalysis', () => ({
  stockAnalysisApi: {
    createTask: mocks.createTask,
    getTask: mocks.getTask,
    getTaskResult: mocks.getTaskResult,
    getLatestResult: mocks.getLatestResult,
    getSignalHistory: mocks.getSignalHistory,
    getSignalSummary: mocks.getSignalSummary,
    cancelTask: mocks.cancelTask,
    exportReport: mocks.exportReport,
  },
}))

vi.mock('@/api/aiObservability', () => ({
  aiObservabilityApi: {
    getMyAvailableModels: mocks.getMyAvailableModels,
  },
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: mocks.messageSuccess,
    warning: mocks.messageWarning,
    error: mocks.messageError,
  },
}))

const baseTask = {
  task_id: 'task-1',
  status: 'pending',
  symbol: '000001.SZ',
  market_type: 'A股',
  analysis_date: '2026-06-20',
  research_depth: '标准',
  selected_modules: ['market', 'fundamentals', 'news', 'risk'],
  progress: 0,
  current_step: 'created',
  message: null,
  created_at: '2026-06-20T00:00:00Z',
  started_at: null,
  completed_at: null,
  error_message: null,
  report_id: null,
}

function mountPage() {
  return mount(StockAnalysisPage, {
    global: {
      stubs: elStubs,
    },
  })
}

describe('StockAnalysisPage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getMyAvailableModels.mockResolvedValue({
      providers: [],
      models: [{ provider: 'openai', model: 'gpt-4.1', display_name: 'GPT-4.1' }],
      preferences: { provider: 'openai', model: 'gpt-4.1' },
    })
    mocks.createTask.mockResolvedValue(baseTask)
    mocks.getTask.mockResolvedValue(baseTask)
    mocks.getLatestResult.mockResolvedValue(null)
    mocks.getSignalHistory.mockResolvedValue({ items: [], next_cursor: null })
    mocks.getSignalSummary.mockResolvedValue({
      symbol: '000001.SZ',
      horizon: 20,
      actioned_generated_count: 0,
      actioned_scorable_count: 0,
      actioned_success_count: 0,
      actioned_success_rate: null,
      coverage_rate: null,
      maturity_rate: null,
      actions: [],
      confidence_bins: [],
    })
    mocks.cancelTask.mockResolvedValue({ ...baseTask, status: 'cancelled' })
  })

  it('renders a standalone single-stock analysis workspace instead of chat', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('AI股票')
    expect(wrapper.text()).toContain('股票代码')
    expect(wrapper.text()).toContain('分析配置')
    expect(wrapper.text()).toContain('研究模块')
    expect(wrapper.text()).toContain('开始智能分析')
    expect(wrapper.text()).toContain('预测成绩单')
    expect(wrapper.text()).toContain('历史预测')
    expect(wrapper.text()).not.toContain('AI 助手对话')
  })

  it('restores the latest completed report and its export actions on mount', async () => {
    mocks.getLatestResult.mockResolvedValue({
      task: {
        ...baseTask,
        status: 'completed',
        progress: 100,
        current_step: 'completed',
        report_id: 'latest-report-1',
      },
      report: {
        meta: { symbol: '000001.SZ', symbol_name: '平安银行', market_type: 'A股' },
        executive_summary: '这是最近一次成功分析。',
        decision: { label: '持有', confidence_score: 0.62, risk_level: '中等' },
        sections: [],
      },
    })

    const wrapper = mountPage()
    await flushPromises()

    expect(mocks.getLatestResult).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.report-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('平安银行')
    expect(wrapper.find('.export-actions').text()).toContain('PDF')
    expect(mocks.getSignalHistory).toHaveBeenCalledWith('000001.SZ')
    expect(mocks.getSignalSummary).toHaveBeenCalledWith('000001.SZ')
  })

  it('creates stock analysis task from the form defaults', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))
    expect(startButton).toBeDefined()
    await startButton!.trigger('click')
    await flushPromises()

    expect(mocks.createTask).toHaveBeenCalledWith({
      symbol: '000001.SZ',
      market_type: 'A股',
      analysis_date: expect.any(String),
      research_depth: '标准',
      selected_modules: ['market', 'fundamentals', 'news', 'risk'],
      include_sentiment: false,
      include_risk: true,
      language: 'zh-CN',
      model_id: 'openai:gpt-4.1',
    })
    expect(wrapper.text()).toContain('分析任务已提交')
  })

  it('updates selected modules when research depth changes', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      form: { researchDepth: string; selectedModules: string[] }
    }

    expect(vm.form.selectedModules).toEqual(['market', 'fundamentals', 'news', 'risk'])

    vm.form.researchDepth = '快速'
    await nextTick()
    expect(vm.form.selectedModules).toEqual(['market'])

    vm.form.researchDepth = '深度'
    await nextTick()
    expect(vm.form.selectedModules).toEqual(['market', 'fundamentals', 'news', 'social', 'risk'])

    vm.form.researchDepth = '全面'
    await nextTick()
    expect(vm.form.selectedModules).toEqual(['market', 'fundamentals', 'news', 'social', 'risk'])
  })

  it('renders completed report sections as sanitized Markdown instead of raw syntax', async () => {
    mocks.createTask.mockResolvedValue({
      ...baseTask,
      status: 'completed',
      progress: 100,
      report_id: 'report-1',
    })
    mocks.getTaskResult.mockResolvedValue({
      task_id: 'task-1',
      report_id: 'report-1',
      status: 'completed',
      report: {
        meta: { symbol: '000001.SZ', symbol_name: '平安银行' },
        executive_summary: '结论：保持审慎。',
        decision: { label: '持有', confidence_score: 0.62, risk_level: '中等' },
        sections: [
          {
            id: 'technical',
            title: '技术与市场分析',
            summary: '# 盘面结论\n\n**趋势：** 区间震荡。',
            findings: [],
          },
        ],
      },
    })

    const wrapper = mountPage()
    await flushPromises()
    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))
    await startButton!.trigger('click')
    await flushPromises()

    const rendered = wrapper.find('.report-section .report-markdown-content')
    expect(rendered.exists()).toBe(true)
    expect(rendered.html()).toContain('<h1>盘面结论</h1>')
    expect(rendered.html()).toContain('<strong>趋势：</strong> 区间震荡。')
  })

  it('rejects an empty symbol or an empty module selection without creating a task', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      form: { symbol: string; selectedModules: string[] }
    }
    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))

    vm.form.symbol = '   '
    await nextTick()
    await startButton!.trigger('click')
    expect(mocks.messageWarning).toHaveBeenCalledWith('请输入股票代码')
    expect(mocks.createTask).not.toHaveBeenCalled()

    vm.form.symbol = '000001.SZ'
    vm.form.selectedModules = []
    await nextTick()
    await startButton!.trigger('click')
    expect(mocks.messageWarning).toHaveBeenLastCalledWith('请至少选择一个研究模块')
    expect(mocks.createTask).not.toHaveBeenCalled()
  })

  it('reports task submission failure and clears the submitting state', async () => {
    mocks.createTask.mockRejectedValueOnce(new Error('service unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))

    await startButton!.trigger('click')
    await flushPromises()

    expect(mocks.createTask).toHaveBeenCalledWith(expect.objectContaining({ symbol: '000001.SZ' }))
    expect(mocks.messageError).toHaveBeenCalledWith('提交分析任务失败')
    expect(wrapper.find('.runtime-panel').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('分析任务已提交')
    expect((wrapper.vm as unknown as { submitting: boolean }).submitting).toBe(false)
    wrapper.unmount()
  })

  it('cancels a pending task and reflects the server terminal status', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))
    await startButton!.trigger('click')
    await flushPromises()

    const cancelButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('取消任务'))
    expect(cancelButton).toBeDefined()
    await cancelButton!.trigger('click')
    await flushPromises()

    expect(mocks.cancelTask).toHaveBeenCalledWith('task-1')
    expect(wrapper.text()).toContain('已取消')
    expect(wrapper.findAll('button').some((button) => button.text().includes('取消任务'))).toBe(false)
    wrapper.unmount()
  })

  it('keeps the pending task visible when cancellation fails', async () => {
    mocks.cancelTask.mockRejectedValueOnce(new Error('cancel endpoint unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    const startButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('开始智能分析'))
    await startButton!.trigger('click')
    await flushPromises()

    const cancelButton = wrapper
      .findAll('button')
      .find((button) => button.text().includes('取消任务'))
    await cancelButton!.trigger('click')
    await flushPromises()

    expect(mocks.cancelTask).toHaveBeenCalledWith('task-1')
    expect(mocks.messageError).toHaveBeenCalledWith('取消任务失败')
    expect((wrapper.vm as unknown as { currentTask: { task_id: string; status: string } }).currentTask)
      .toMatchObject({ task_id: 'task-1', status: 'pending' })
    expect(wrapper.findAll('button').some((button) => button.text().includes('取消任务'))).toBe(true)
    wrapper.unmount()
  })

  it('downloads a report blob and reports an export API failure', async () => {
    mocks.getLatestResult.mockResolvedValue({
      task: { ...baseTask, status: 'completed', report_id: 'latest-report-1' },
      report: { meta: { symbol: '000001.SZ' }, sections: [] },
    })
    mocks.exportReport
      .mockRejectedValueOnce(new Error('export service unavailable'))
      .mockResolvedValueOnce(new Blob(['report markdown'], { type: 'text/markdown' }))
    const createObjectURL = vi.fn(() => 'blob:stock-report')
    const revokeObjectURL = vi.fn()
    const clickLink = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    const wrapper = mountPage()
    await flushPromises()
    const exportButtons = wrapper.findAll('.export-actions button')

    await exportButtons.find((button) => button.text() === 'PDF')!.trigger('click')
    await flushPromises()
    expect(mocks.exportReport).toHaveBeenNthCalledWith(1, 'latest-report-1', 'pdf')
    expect(mocks.messageError).toHaveBeenCalledWith('导出报告失败')

    await exportButtons.find((button) => button.text() === 'HTML')!.trigger('click')
    await flushPromises()

    expect(mocks.exportReport).toHaveBeenNthCalledWith(2, 'latest-report-1', 'html')
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
    expect(clickLink).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:stock-report')
    wrapper.unmount()
  })
})
