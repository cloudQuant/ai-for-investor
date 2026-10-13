// @vitest-environment jsdom
// DOMPurify relies on real Node.prototype.nodeName semantics; happy-dom can remove allowed tags.
// Keep jsdom scoped to Markdown tests; other frontend tests remain in happy-dom.
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ChatMessageBubble from '@/components/aichat/ChatMessageBubble.vue'
import type { KBChatMessage } from '@/stores/kbChat'
import type {
  KBCitation,
  KBRetrievalDiagnostics,
  KBStockAnalysisReport,
  KBStockAnalysisTask,
  KBStrategyDraft,
} from '@/api/kbChat'
import type { DraftWorkspaceExecutionState } from '@/composables/useStrategyDraftWorkspaceExecution'

function mountMessage(
  message: KBChatMessage,
  options: {
    execution?: DraftWorkspaceExecutionState
    knowledgeBaseId?: string | null
    strategyWorkflowEnabled?: boolean
  } = {},
) {
  return mount(ChatMessageBubble, {
    props: {
      message,
      saving: false,
      saved: false,
      added: false,
      runningBacktest: false,
      refreshingStatus: false,
      generatingReport: false,
      ...options,
    },
  })
}

function makeStrategyDraft(code = [
  'import backtrader as bt',
  'class Momentum(bt.Strategy):',
  '    def __init__(self):',
  '        self.sma = bt.indicators.SMA(self.data.close, period=20)',
  '    def next(self):',
  '        if not self.position:',
  '            self.buy()',
].join('\n')): KBStrategyDraft {
  return {
    name: 'Momentum',
    description: 'A typed strategy draft for UI tests.',
    code,
    params: {},
    category: 'trend',
    assumptions: ['Daily bars are available'],
    risk_points: ['Price gaps can change execution'],
    data_source: { type: 'akshare', timeframe: '1d', timeframe_n: 1 },
    backtest_defaults: {
      initial_cash: 100_000,
      commission: 0.001,
      annual_days: 252,
      calc_method: 'simple',
      weight_mode: 'equal',
    },
    execution_plan: { workspace_type: 'research', run_parallel: false },
  }
}

describe('ChatMessageBubble', () => {
  it('renders assistant responses as sanitized Markdown', () => {
    const wrapper = mountMessage({
      role: 'assistant',
      content: [
        '## 直接结论',
        '',
        '**贝叶斯网络风险治理**需要持续诊断。',
        '',
        '- 检查模型结构',
        '- 验证采样稳定性',
        '',
        '```python',
        'risk_score = 0.1',
        '```',
      ].join('\n'),
    })

    const content = wrapper.find('.message-content')
    expect(content.find('h2').text()).toBe('直接结论')
    expect(content.find('strong').text()).toBe('贝叶斯网络风险治理')
    expect(content.findAll('li')).toHaveLength(2)
    expect(content.find('pre code').text()).toContain('risk_score = 0.1')
    expect(content.text()).not.toContain('**')
  })

  it('keeps user input as plain text', () => {
    const wrapper = mountMessage({ role: 'user', content: '**不要被渲染**' })

    expect(wrapper.find('.message-content').text()).toBe('**不要被渲染**')
    expect(wrapper.find('.message-content strong').exists()).toBe(false)
  })

  it('renders assistant diagnostics, retrieval details and citations with observable actions', async () => {
    const citations: KBCitation[] = [
      {
        document_id: 'risk-policy-17',
        document_title: '风险控制规范',
        chunk_id: 'risk-policy-17-2',
        chunk_index: 2,
        similarity: 0.92,
        content: '单笔风险需要持续监控。',
      },
      { content: '无文档标识的引用片段' },
    ]
    const diagnostics: KBRetrievalDiagnostics = {
      retrieval_profile: 'precision',
      search_mode: 'hybrid',
      search_query: '仓位风险约束',
      query_rewritten: true,
      applied_top_k: 4,
      applied_min_similarity: 0.42,
      indexed_documents: 2,
      total_indexable_documents: 5,
      history_messages_used: 1,
    }
    const content = '结论已核对引用。'
    const wrapper = mountMessage({
      role: 'assistant',
      content,
      reasoning: '先检查索引覆盖，再解释匹配依据。',
      reasonCode: 'ai_provider_failed',
      diagnosticMessage: '当前请求未能完成模型生成。',
      diagnostics,
      citations,
    })

    expect(wrapper.get('.diagnostic-box').classes()).toContain('ai_provider_failed')
    expect(wrapper.get('.diagnostic-box').text()).toContain('当前请求未能完成模型生成。')
    expect(wrapper.get('.retrieval-box').text()).toContain('仓位风险约束')
    expect(wrapper.get('.retrieval-box').text()).toContain('hybrid')
    expect(wrapper.get('.retrieval-box').text()).toContain('2/5')
    expect(wrapper.get('.retrieval-box').text()).toContain('已重写查询')
    expect(wrapper.get('.reasoning-box').text()).toContain('先检查索引覆盖')

    const citationButtons = wrapper.findAll('[data-test="citation-chip"]')
    expect(citationButtons).toHaveLength(2)
    expect(citationButtons[0].text()).toContain('风险控制规范')
    expect(citationButtons[0].text()).toContain('92%')
    expect(citationButtons[1].attributes('disabled')).toBeDefined()
    await citationButtons[0].trigger('click')
    await wrapper.get('.message-head-actions button').trigger('click')

    expect(wrapper.emitted('jumpCitation')).toEqual([['risk-policy-17']])
    expect(wrapper.emitted('copyMessage')).toEqual([[content]])
    wrapper.unmount()
  })

  it('shows draft readiness and emits workflow actions from visible controls', async () => {
    const wrapper = mountMessage({
      role: 'assistant',
      content: '已生成策略草案。',
      assistantMode: 'backtrader_strategy',
      strategyDraft: makeStrategyDraft(),
    }, { strategyWorkflowEnabled: true })

    expect(wrapper.get('.message-badge.success').text()).toContain('可保存为策略')
    expect(wrapper.findAll('.workflow-hover-actions button')).toHaveLength(5)
    expect(wrapper.findAll('.workflow-next-actions button')).toHaveLength(3)
    expect(wrapper.find('.workflow-next-actions').text()).toContain('回测策略')

    await wrapper.find('.workflow-next-actions button').trigger('click')
    await wrapper.find('.workflow-hover-actions button').trigger('click')
    expect(wrapper.emitted('strategyWorkflowAction')).toEqual([['backtest'], ['rethink']])
    wrapper.unmount()

    const incompleteDraft = mountMessage({
      role: 'assistant',
      content: '草案代码尚未补全。',
      strategyDraft: makeStrategyDraft(''),
    })
    expect(incompleteDraft.get('.message-badge.warning').text()).toContain('草稿待补全')
    expect(incompleteDraft.find('.workflow-next-actions').exists()).toBe(false)
    incompleteDraft.unmount()
  })

  it('renders stock task and report states and emits the report continuation prompt', async () => {
    const task: KBStockAnalysisTask = {
      task_id: 'task-stock-1',
      symbol: '600519.SH',
      status: 'completed',
      progress: 100,
      current_step: 'report_ready',
      message: '分析报告已生成。',
    }
    const report: KBStockAnalysisReport = {
      report_id: 'report-stock-1',
      symbol: '600519.SH',
      summary: '盈利质量稳定，仍需关注估值波动。',
      decision_label: '观察',
      risk_level: '中等',
      confidence_score: 0.81,
      export_formats: ['markdown'],
    }
    const message: KBChatMessage = {
      role: 'assistant',
      content: '个股分析完成。',
      stockAnalysisTask: task,
      stockAnalysisReport: report,
    }
    const wrapper = mountMessage(message)

    expect(wrapper.get('.stock-task-card').text()).toContain('completed')
    expect(wrapper.get('.stock-task-card').text()).toContain('分析报告已生成。')
    expect(wrapper.get('.stock-analysis-card').text()).toContain('盈利质量稳定')
    expect(wrapper.get('.stock-analysis-card').text()).toContain('81%')

    await wrapper.get('.stock-actions button').trigger('click')
    expect(wrapper.emitted('continueStrategyIdea')).toHaveLength(1)
    expect(wrapper.emitted('continueStrategyIdea')?.[0]?.[0]).toContain('600519.SH 股票分析报告')
    wrapper.unmount()
  })

  it('selects the review workflow after a completed execution result', async () => {
    const execution: DraftWorkspaceExecutionState = {
      workspaceId: 'workspace-1',
      workspaceName: '研究工作区',
      unitId: 'unit-1',
      strategyId: 'strategy-1',
      runStatus: 'completed',
      lastTaskId: 'task-1',
      report: null,
      analysis: null,
    }
    const wrapper = mountMessage({
      role: 'assistant',
      content: '回测已完成。',
      assistantMode: 'knowledge_qa',
    }, { strategyWorkflowEnabled: true, execution })

    const nextActions = wrapper.findAll('.workflow-next-actions button')
    expect(nextActions).toHaveLength(3)
    expect(wrapper.find('.workflow-next-actions').text()).toContain('审查策略')
    await nextActions[0].trigger('click')
    expect(wrapper.emitted('strategyWorkflowAction')).toEqual([['review']])
    wrapper.unmount()
  })
})
