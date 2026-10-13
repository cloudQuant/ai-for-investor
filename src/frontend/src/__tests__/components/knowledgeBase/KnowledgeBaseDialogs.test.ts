import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { reactive } from 'vue'

import type { KBDocumentItem, KnowledgeBaseItem, KnowledgeBaseSettings } from '@/api/knowledgeBase'
import KnowledgeBaseDialogs from '@/views/knowledge-base/KnowledgeBaseDialogs.vue'

const document = {
  id: 'doc-1',
  knowledge_base_id: 'kb-1',
  title: 'Research notes',
  content: 'Notes',
  content_type: 'markdown',
  is_folder: false,
  parent_id: null,
  sort_order: 0,
  status: 'draft',
  index_status: 'not_indexed',
  created_at: '2026-04-23T00:00:00Z',
  updated_at: '2026-04-23T00:00:00Z',
} satisfies KBDocumentItem

const knowledgeBase = {
  id: 'kb-1',
  owner_id: 'user-1',
  name: 'Research library',
  document_count: 1,
  is_public: false,
  created_at: '2026-04-23T00:00:00Z',
  updated_at: '2026-04-23T00:00:00Z',
} satisfies KnowledgeBaseItem

const settings: KnowledgeBaseSettings = {
  retrieval_profile: 'quant_research',
  search_mode: 'hybrid',
  default_top_k: 8,
  min_similarity: 0.08,
  title_weight: 0.35,
  keyword_weight: 0.35,
  phrase_weight: 0.2,
  recency_weight: 0.1,
  max_context_chunks: 6,
  use_conversation_memory: true,
  conversation_lookback_messages: 6,
  prioritize_title_matches: true,
  prefer_recent_documents: true,
  quant_focus: 'strategy_research',
  system_prompt_suffix: '',
}

function createProps() {
  const state = reactive({
    bulkDialog: { open: true, mode: 'delete' as const },
    bulkDialogMessage: 'Delete 1 document?',
    createDialog: { open: true, isFolder: false, title: '', content: '', parentId: null as string | null },
    renameDialog: { open: true, target: document, title: document.title },
    importDialog: { open: true, title: '', content: '' },
    deleteDialog: { open: true, target: document },
    knowledgeBaseRenameDialog: { open: true, target: knowledgeBase, name: knowledgeBase.name },
    knowledgeBaseDeleteDialog: { open: true, target: knowledgeBase },
    knowledgeBaseSettingsDialog: { open: true, form: { ...settings } },
  })
  const actions = {
    closeBulkDialog: vi.fn(),
    closeCreateDialog: vi.fn(),
    closeDeleteDialog: vi.fn(),
    closeImportDialog: vi.fn(),
    closeKnowledgeBaseDeleteDialog: vi.fn(),
    closeKnowledgeBaseRenameDialog: vi.fn(),
    closeKnowledgeBaseSettingsDialog: vi.fn(),
    closeRenameDialog: vi.fn(),
    submitBulkDialog: vi.fn(),
    submitCreateDialog: vi.fn(),
    submitDeleteDialog: vi.fn(),
    submitImportDialog: vi.fn(),
    submitKnowledgeBaseDeleteDialog: vi.fn(),
    submitKnowledgeBaseRenameDialog: vi.fn(),
    submitKnowledgeBaseSettingsDialog: vi.fn(),
    submitRenameDialog: vi.fn(),
  }
  return { state, actions, props: { ...state, ...actions } }
}

describe('KnowledgeBaseDialogs', () => {
  it('edits create and import forms and dispatches the corresponding actions', async () => {
    const { state, actions, props } = createProps()
    const wrapper = mount(KnowledgeBaseDialogs, { props })
    const cards = wrapper.findAll('.kb-dialog-card')

    expect(cards).toHaveLength(8)
    await cards[0].find('input').setValue('New document')
    await cards[0].find('textarea').setValue('Document body')
    await cards[2].find('input').setValue('Imported brief')
    await cards[2].find('textarea').setValue('Imported body')

    expect(state.createDialog.title).toBe('New document')
    expect(state.createDialog.content).toBe('Document body')
    expect(state.importDialog.title).toBe('Imported brief')
    expect(state.importDialog.content).toBe('Imported body')

    await cards[0].findAll('button').at(-1)!.trigger('click')
    await cards[2].findAll('button').at(-1)!.trigger('click')
    expect(actions.submitCreateDialog).toHaveBeenCalledOnce()
    expect(actions.submitImportDialog).toHaveBeenCalledOnce()
  })

  it('wires rename, delete, bulk, and settings dialogs to their page actions', async () => {
    const { actions, props } = createProps()
    const wrapper = mount(KnowledgeBaseDialogs, { props })
    const cards = wrapper.findAll('.kb-dialog-card')

    await cards[1].find('input').setValue('Renamed document')
    await cards[5].find('input').setValue('Renamed library')
    await cards[7].find('input[type="number"]').setValue('12')

    await cards[1].findAll('button').at(-1)!.trigger('click')
    await cards[3].findAll('button').at(-1)!.trigger('click')
    await cards[4].findAll('button').at(-1)!.trigger('click')
    await cards[5].findAll('button').at(-1)!.trigger('click')
    await cards[6].findAll('button').at(-1)!.trigger('click')
    await cards[7].findAll('button').at(-1)!.trigger('click')

    expect(props.renameDialog.title).toBe('Renamed document')
    expect(props.knowledgeBaseRenameDialog.name).toBe('Renamed library')
    expect(props.knowledgeBaseSettingsDialog.form.default_top_k).toBe(12)
    expect(actions.submitRenameDialog).toHaveBeenCalledOnce()
    expect(actions.submitBulkDialog).toHaveBeenCalledOnce()
    expect(actions.submitDeleteDialog).toHaveBeenCalledOnce()
    expect(actions.submitKnowledgeBaseRenameDialog).toHaveBeenCalledOnce()
    expect(actions.submitKnowledgeBaseDeleteDialog).toHaveBeenCalledOnce()
    expect(actions.submitKnowledgeBaseSettingsDialog).toHaveBeenCalledOnce()

    for (const card of cards) {
      await card.find('button[aria-label="关闭对话框"]').trigger('click')
    }
    expect(actions.closeBulkDialog).toHaveBeenCalledOnce()
    expect(actions.closeCreateDialog).toHaveBeenCalledOnce()
    expect(actions.closeDeleteDialog).toHaveBeenCalledOnce()
    expect(actions.closeImportDialog).toHaveBeenCalledOnce()
    expect(actions.closeKnowledgeBaseDeleteDialog).toHaveBeenCalledOnce()
    expect(actions.closeKnowledgeBaseRenameDialog).toHaveBeenCalledOnce()
    expect(actions.closeKnowledgeBaseSettingsDialog).toHaveBeenCalledOnce()
    expect(actions.closeRenameDialog).toHaveBeenCalledOnce()
  })
})
