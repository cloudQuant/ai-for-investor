import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

import { ElMessage } from 'element-plus'
import { useAIChatPage } from '@/composables/useAIChatPage'

const mocks = vi.hoisted(() => ({
  routeQuery: {} as Record<string, unknown>,
  routerPush: vi.fn(),
  confirm: vi.fn(),
  resetExecutions: vi.fn(),
  getMyAvailableModels: vi.fn(),
  knowledgeBases: [] as unknown[],
  documents: [] as unknown[],
  conversations: [] as unknown[],
  messages: [] as unknown[],
  currentConversationId: null as string | null,
  chatLoading: false,
  fetchKnowledgeBases: vi.fn(),
  selectKnowledgeBase: vi.fn(),
  fetchConversations: vi.fn(),
  fetchHistory: vi.fn(),
  deleteConversation: vi.fn(),
  resetConversationState: vi.fn(),
  sendMessage: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: mocks.routeQuery }),
  useRouter: () => ({ push: mocks.routerPush }),
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
  ElMessageBox: {
    confirm: mocks.confirm,
  },
}))

vi.mock('@/api/aiObservability', () => ({
  aiObservabilityApi: {
    getMyAvailableModels: mocks.getMyAvailableModels,
  },
}))

vi.mock('@/api/strategy', () => ({
  strategyApi: {
    create: vi.fn(),
    addCopilotDraftToWorkspace: vi.fn(),
    backtestCopilotDraft: vi.fn(),
  },
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    list: vi.fn(),
    runUnits: vi.fn(),
    getUnitsStatus: vi.fn(),
    createReport: vi.fn(),
  },
}))

vi.mock('@/stores/knowledgeBase', () => ({
  useKnowledgeBaseStore: () => ({
    knowledgeBases: mocks.knowledgeBases,
    currentKnowledgeBase: mocks.knowledgeBases[0] ?? null,
    documents: mocks.documents,
    fetchKnowledgeBases: mocks.fetchKnowledgeBases,
    selectKnowledgeBase: mocks.selectKnowledgeBase,
  }),
}))

vi.mock('@/stores/kbChat', () => ({
  useKBChatStore: () => ({
    conversations: mocks.conversations,
    messages: mocks.messages,
    currentConversationId: mocks.currentConversationId,
    loading: mocks.chatLoading,
    fetchConversations: mocks.fetchConversations,
    fetchHistory: mocks.fetchHistory,
    deleteConversation: mocks.deleteConversation,
    resetConversationState: mocks.resetConversationState,
    sendMessage: mocks.sendMessage,
  }),
}))

vi.mock('@/composables/useStrategyDraftWorkspaceExecution', async () => {
  const { ref } = await import('vue')
  return {
    useStrategyDraftWorkspaceExecution: () => ({
      workspaceExecutions: ref([]),
      runningBacktestIndex: ref(null),
      refreshingStatusIndex: ref(null),
      generatingReportIndex: ref(null),
      buildReportConfigFromDraft: vi.fn(),
      recordAddedExecution: vi.fn(),
      recordBacktestExecution: vi.fn(),
      runExecution: vi.fn(),
      refreshExecution: vi.fn(),
      generateReport: vi.fn(),
      resetExecutions: mocks.resetExecutions,
    }),
  }
})

let page: ReturnType<typeof useAIChatPage>
let unmount: (() => void) | undefined

async function mountPage() {
  const wrapper = mount(defineComponent({
    setup() {
      page = useAIChatPage()
      return () => h('div')
    },
  }))
  unmount = () => wrapper.unmount()
  await flushPromises()
  return wrapper
}

describe('useAIChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.routeQuery = {}
    mocks.knowledgeBases = []
    mocks.documents = []
    mocks.conversations = []
    mocks.messages = []
    mocks.currentConversationId = null
    mocks.chatLoading = false
    localStorage.removeItem('ai_for_investor:ai_chat:selected_knowledge_base_id')
    mocks.getMyAvailableModels.mockResolvedValue({
      providers: [],
      models: [],
      preferences: { provider: null, model: null },
    })
    mocks.fetchKnowledgeBases.mockResolvedValue(undefined)
    mocks.selectKnowledgeBase.mockResolvedValue(undefined)
    mocks.fetchConversations.mockResolvedValue({ items: [] })
    mocks.fetchHistory.mockResolvedValue(undefined)
    mocks.deleteConversation.mockResolvedValue(undefined)
    mocks.sendMessage.mockResolvedValue(undefined)
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('keeps questions blocked when no knowledge base is available', async () => {
    await mountPage()

    page.question.value = '  How does this strategy work?  '
    expect(page.currentKnowledgeBaseId.value).toBe('')
    expect(page.canSubmitQuestion.value).toBe(false)

    await page.handleAsk()

    expect(mocks.fetchKnowledgeBases).toHaveBeenCalledOnce()
    expect(mocks.sendMessage).not.toHaveBeenCalled()
    expect(page.question.value).toBe('  How does this strategy work?  ')
  })

  it('sends a trimmed question with the selected collection and reports send failures', async () => {
    const knowledgeBase = {
      id: 'kb-1',
      owner_id: 'user-1',
      name: 'Research',
      description: null,
      document_count: 0,
      is_public: false,
      created_at: '2026-04-23T00:00:00Z',
      updated_at: '2026-04-23T00:00:00Z',
    }
    mocks.knowledgeBases = [knowledgeBase]
    mocks.getMyAvailableModels.mockResolvedValue({
      providers: [],
      models: [
        { provider: 'openai', model: 'gpt-test', display_name: 'GPT test' },
      ],
      preferences: { provider: 'openai', model: 'gpt-test' },
    })

    await mountPage()
    expect(page.selectedKnowledgeBaseId.value).toBe('kb-1')
    expect(page.selectedSessionModelKey.value).toBe('openai::gpt-test')
    expect(page.canSubmitQuestion.value).toBe(false)
    expect(mocks.selectKnowledgeBase).toHaveBeenCalledWith('kb-1')
    expect(mocks.fetchConversations).toHaveBeenCalledWith('kb-1')

    page.question.value = '  How does the strategy enter?  '
    expect(page.canSubmitQuestion.value).toBe(true)
    await page.handleAsk()

    expect(mocks.sendMessage).toHaveBeenCalledWith('kb-1', 'How does the strategy enter?', {
      assistantMode: 'knowledge_qa',
      thinkingMode: false,
      modelId: 'openai::gpt-test',
    })
    expect(page.question.value).toBe('')

    mocks.sendMessage.mockRejectedValueOnce(new Error('service unavailable'))
    page.question.value = '  Retry question  '
    await page.handleAsk()
    expect(ElMessage.error).toHaveBeenCalled()
  })

  it('surfaces collection and conversation loading errors while preserving the selected collection', async () => {
    mocks.knowledgeBases = [{
      id: 'kb-1',
      owner_id: 'user-1',
      name: 'Research',
      description: null,
      document_count: 0,
      is_public: false,
      created_at: '2026-04-23T00:00:00Z',
      updated_at: '2026-04-23T00:00:00Z',
    }]
    mocks.selectKnowledgeBase.mockRejectedValueOnce(new Error('document list unavailable'))
    mocks.fetchConversations.mockRejectedValueOnce(new Error('conversation list unavailable'))

    await mountPage()

    expect(page.selectedKnowledgeBaseId.value).toBe('kb-1')
    expect(ElMessage.error).toHaveBeenCalledTimes(2)
  })

  it('honors confirmation before deleting a conversation and resets the active session', async () => {
    const knowledgeBase = {
      id: 'kb-1',
      owner_id: 'user-1',
      name: 'Research',
      description: null,
      document_count: 0,
      is_public: false,
      created_at: '2026-04-23T00:00:00Z',
      updated_at: '2026-04-23T00:00:00Z',
    }
    mocks.knowledgeBases = [knowledgeBase]
    mocks.currentConversationId = 'conv-1'
    mocks.confirm.mockRejectedValueOnce(new Error('user cancelled'))
    mocks.confirm.mockResolvedValueOnce('confirm')

    await mountPage()
    page.question.value = 'Current question'
    mocks.resetConversationState.mockClear()

    await page.handleDeleteConversation('conv-1')
    expect(mocks.deleteConversation).not.toHaveBeenCalled()
    expect(mocks.resetConversationState).not.toHaveBeenCalled()

    await page.handleDeleteConversation('conv-1')
    expect(mocks.deleteConversation).toHaveBeenCalledWith('conv-1')
    expect(mocks.resetConversationState).toHaveBeenCalledOnce()
    expect(page.question.value).toBe('')
    expect(ElMessage.success).toHaveBeenCalled()
  })

  it('requires a citation target and opens the document in the active collection', async () => {
    await mountPage()
    await page.handleJumpToCitation()
    expect(ElMessage.warning).toHaveBeenCalled()

    page.selectedKnowledgeBaseId.value = 'kb-1'
    await page.handleJumpToCitation('doc-1')

    expect(mocks.routerPush).toHaveBeenCalledWith({ path: '/ai/knowledge-base/kb-1/documents/doc-1' })
  })

  it('clears message state and workspace draft state when starting a new conversation', async () => {
    await mountPage()
    page.question.value = 'Question in the old session'
    page.savedStrategyIds.value = { 2: 'strategy-2' }
    page.addedWorkspaceUnitIds.value = { 2: 'unit-2' }
    page.showAddToWorkspaceDialog.value = true
    page.researchWorkspaces.value = [{ id: 'ws-1' } as never]
    page.addingToWorkspace.value = true
    page.workspaceDraftForm.value = {
      workspaceId: 'ws-1',
      symbol: '000001.SZ',
      symbolName: '平安银行',
      timeframe: '1d',
      groupName: 'Old strategy',
    }

    page.handleNewConversation()

    expect(mocks.resetConversationState).toHaveBeenCalledOnce()
    expect(mocks.resetExecutions).toHaveBeenCalledOnce()
    expect(page.question.value).toBe('')
    expect(page.savedStrategyIds.value).toEqual({})
    expect(page.addedWorkspaceUnitIds.value).toEqual({})
    expect(page.showAddToWorkspaceDialog.value).toBe(false)
    expect(page.researchWorkspaces.value).toEqual([])
    expect(page.addingToWorkspace.value).toBe(false)
    expect(page.workspaceDraftForm.value).toEqual({
      workspaceId: '',
      symbol: '',
      symbolName: '',
      timeframe: '1d',
      groupName: '',
    })
  })

  it('loads a requested collection, filters conversation history, and uses the available model fallback', async () => {
    const knowledgeBases = [
      {
        id: 'kb-1', owner_id: 'user-1', name: 'Market notes', description: null,
        document_count: 1, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
      {
        id: 'kb-2', owner_id: 'user-1', name: 'Earnings research', description: null,
        document_count: 2, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
    ]
    mocks.knowledgeBases = knowledgeBases
    mocks.routeQuery = { kbId: 'kb-2', prompt: 'Explain the latest earnings' }
    mocks.conversations = [
      { id: 'conv-1', title: 'Market outlook' },
      { id: 'conv-2', title: 'Quarterly earnings review' },
    ]
    mocks.documents = [
      { id: 'folder-1', is_folder: true, index_status: 'indexed' },
      { id: 'doc-1', is_folder: false, index_status: 'indexed' },
      { id: 'doc-2', is_folder: false, index_status: 'failed' },
    ]
    mocks.getMyAvailableModels.mockResolvedValue({
      providers: [{ id: 'openai', name: 'OpenAI' }],
      models: [{ provider: 'openai', model: 'gpt-current', display_name: 'GPT current' }],
      preferences: { provider: 'retired-provider', model: 'retired-model' },
      default_model_key: 'openai::gpt-current',
    })

    await mountPage()

    expect(page.selectedKnowledgeBaseId.value).toBe('kb-2')
    expect(page.currentKnowledgeBaseName.value).toBe('Earnings research')
    expect(page.requestKnowledgeBaseId.value).toBe('kb-2')
    expect(page.question.value).toBe('Explain the latest earnings')
    expect(page.selectedSessionModelKey.value).toBe('openai::gpt-current')
    expect(page.sessionModelOptions.value).toHaveLength(1)
    expect(page.indexedDocumentCount.value).toBe(1)
    expect(page.hasUnindexedDocuments.value).toBe(true)

    page.conversationSearch.value = '  EARNINGS '
    expect(page.filteredConversations.value.map(conversation => conversation.id)).toEqual(['conv-2'])
    page.conversationSearch.value = ' '
    expect(page.filteredConversations.value).toHaveLength(2)
    await page.handleSelectConversation('conv-2')
    expect(mocks.fetchHistory).toHaveBeenCalledWith('conv-2')

    page.thinkingMode.value = true
    page.question.value = 'Summarize the risk factors'
    await page.handleAsk()
    expect(mocks.sendMessage).toHaveBeenCalledWith('kb-2', 'Summarize the risk factors', {
      assistantMode: 'knowledge_qa',
      thinkingMode: true,
      modelId: 'openai::gpt-current',
    })
  })

  it('does not send empty or in-flight questions and clears model options after provider loading fails', async () => {
    mocks.knowledgeBases = [{
      id: 'kb-1', owner_id: 'user-1', name: 'Research', description: null,
      document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
    }]
    mocks.getMyAvailableModels.mockRejectedValueOnce(new Error('provider service unavailable'))
    await mountPage()

    expect(page.sessionModelOptions.value).toEqual([])
    expect(page.selectedSessionModelKey.value).toBe('')
    page.question.value = '   '
    expect(page.canSubmitQuestion.value).toBe(false)
    await page.handleAsk()
    expect(mocks.sendMessage).not.toHaveBeenCalled()

    unmount?.()
    unmount = undefined
    mocks.chatLoading = true
    await mountPage()
    page.question.value = 'A valid question'
    expect(page.canSubmitQuestion.value).toBe(false)
    await page.handleAsk()
    expect(mocks.sendMessage).not.toHaveBeenCalled()
  })

  it('migrates a legacy strategy mode route while preserving its prompt', async () => {
    mocks.routeQuery = { mode: 'strategy_review', prompt: 'Review this strategy' }

    await mountPage()

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'InvestmentStrategies',
      query: { prompt: 'Review this strategy', workflow: 'strategy_review' },
    })
    expect(page.selectedAssistantMode.value).toBe('knowledge_qa')
    expect(page.question.value).toBe('')
  })

  it('falls back to the remembered collection when the route requests an unavailable one', async () => {
    mocks.knowledgeBases = [
      {
        id: 'kb-1', owner_id: 'user-1', name: 'Market notes', description: null,
        document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
      {
        id: 'kb-2', owner_id: 'user-1', name: 'Earnings research', description: null,
        document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
    ]
    localStorage.setItem('ai_for_investor:ai_chat:selected_knowledge_base_id', 'kb-2')
    mocks.routeQuery = { kbId: 'deleted-kb' }

    await mountPage()

    expect(page.selectedKnowledgeBaseId.value).toBe('kb-2')
    expect(mocks.selectKnowledgeBase).toHaveBeenCalledWith('kb-2')
  })

  it('loads history and conversations when the selected collection changes', async () => {
    mocks.knowledgeBases = [
      {
        id: 'kb-1', owner_id: 'user-1', name: 'Market notes', description: null,
        document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
      {
        id: 'kb-2', owner_id: 'user-1', name: 'Earnings research', description: null,
        document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
      },
    ]
    await mountPage()
    mocks.resetConversationState.mockClear()
    page.conversationSearch.value = 'stale conversation filter'

    page.selectedKnowledgeBaseId.value = 'kb-2'
    await flushPromises()

    expect(mocks.resetConversationState).toHaveBeenCalledOnce()
    expect(mocks.selectKnowledgeBase).toHaveBeenLastCalledWith('kb-2')
    expect(mocks.fetchConversations).toHaveBeenLastCalledWith('kb-2')
    expect(page.conversationSearch.value).toBe('')
    expect(localStorage.getItem('ai_for_investor:ai_chat:selected_knowledge_base_id')).toBe('kb-2')
  })

  it.each([
    { action: 'rethink', workflow: 'strategy_idea' },
    { action: 'regenerate', workflow: 'backtrader_strategy' },
    { action: 'optimize', workflow: 'backtrader_strategy' },
    { action: 'review', workflow: 'strategy_review' },
  ] as const)('routes the $action action into its strategy workflow', async ({ action, workflow }) => {
    await mountPage()

    await page.handleStrategyWorkflowAction(action, { role: 'assistant', content: 'Generated idea' } as never, 0)

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'InvestmentStrategies',
      query: { prompt: expect.any(String), workflow },
    })
  })

  it('does not open a workflow while a chat response is still loading', async () => {
    mocks.chatLoading = true
    await mountPage()

    await page.handleStrategyWorkflowAction('review', { role: 'assistant', content: 'Generated idea' } as never, 0)

    expect(mocks.routerPush).not.toHaveBeenCalled()
  })

  it('migrates a duplicate-symbol legacy stock route without forwarding an ambiguous symbol', async () => {
    mocks.routeQuery = { mode: 'stock_analysis', symbol: ['000001.SZ', '000002.SZ'] }

    await mountPage()

    expect(mocks.routerPush).toHaveBeenCalledWith({
      name: 'InvestmentStockAnalysis',
      query: { symbol: undefined },
    })
  })

  it('keeps non-current conversation deletion isolated and reports delete failures', async () => {
    mocks.knowledgeBases = [{
      id: 'kb-1', owner_id: 'user-1', name: 'Research', description: null,
      document_count: 0, is_public: false, created_at: '2026-04-23T00:00:00Z', updated_at: '2026-04-23T00:00:00Z',
    }]
    mocks.currentConversationId = 'conv-current'
    mocks.confirm.mockResolvedValue('confirm')
    await mountPage()
    mocks.resetConversationState.mockClear()

    await page.handleDeleteConversation('conv-old')
    expect(mocks.deleteConversation).toHaveBeenCalledWith('conv-old')
    expect(mocks.resetConversationState).not.toHaveBeenCalled()

    mocks.deleteConversation.mockRejectedValueOnce(new Error('delete failed'))
    await page.handleDeleteConversation('conv-current')
    expect(ElMessage.error).toHaveBeenCalled()
    expect(mocks.resetConversationState).not.toHaveBeenCalled()
  })
})
