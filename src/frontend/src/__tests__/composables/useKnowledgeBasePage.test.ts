import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, reactive } from 'vue'

import { ElMessage } from 'element-plus'
import type { KBDocumentItem, KnowledgeBaseItem } from '@/api/knowledgeBase'
import { useKnowledgeBasePage } from '@/composables/useKnowledgeBasePage'

const mocks = vi.hoisted(() => ({
  routeQuery: {} as Record<string, unknown>,
  push: vi.fn(),
  store: {
    knowledgeBases: [] as unknown[],
    currentKnowledgeBase: null as unknown,
    documents: [] as unknown[],
    currentDocument: null as unknown,
    documentDetailLoading: false,
    fetchKnowledgeBases: vi.fn(),
    selectKnowledgeBase: vi.fn(),
    fetchDocumentDetail: vi.fn(),
    clearCurrentDocument: vi.fn(),
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
    updateKnowledgeBase: vi.fn(),
    deleteKnowledgeBase: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: mocks.routeQuery }),
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/stores/knowledgeBase', () => ({
  useKnowledgeBaseStore: () => mocks.store,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

const makeKnowledgeBase = (overrides: Partial<KnowledgeBaseItem> = {}): KnowledgeBaseItem => ({
  id: 'kb-1',
  owner_id: 'user-1',
  name: 'Alpha research',
  description: 'Market notes',
  document_count: 1,
  is_public: false,
  created_at: '2026-04-23T00:00:00Z',
  updated_at: '2026-04-23T00:00:00Z',
  ...overrides,
})

const makeDocument = (overrides: Partial<KBDocumentItem> = {}): KBDocumentItem => ({
  id: 'doc-1',
  knowledge_base_id: 'kb-1',
  title: 'Alpha document',
  content: 'Alpha strategy notes',
  content_type: 'markdown',
  file_path: null,
  is_folder: false,
  parent_id: null,
  sort_order: 0,
  status: 'draft',
  index_status: 'not_indexed',
  indexed_at: null,
  metadata: null,
  created_at: '2026-04-23T00:00:00Z',
  updated_at: '2026-04-23T00:00:00Z',
  ...overrides,
})

let page: ReturnType<typeof useKnowledgeBasePage>
let unmount: (() => void) | undefined

async function mountPage() {
  const wrapper = mount(defineComponent({
    setup() {
      page = useKnowledgeBasePage()
      return () => h('div')
    },
  }))
  unmount = () => wrapper.unmount()
  await flushPromises()
  return wrapper
}

describe('useKnowledgeBasePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.routeQuery = {}
    mocks.store.knowledgeBases = reactive([makeKnowledgeBase(), makeKnowledgeBase({
      id: 'kb-2',
      name: 'Beta research',
      description: 'Alternative notes',
    })])
    mocks.store.currentKnowledgeBase = makeKnowledgeBase()
    mocks.store.documents = reactive([
      makeDocument(),
      makeDocument({
        id: 'doc-2',
        title: 'Beta document',
        content: 'A document about earnings',
        sort_order: 1,
        updated_at: '2026-04-24T00:00:00Z',
      }),
    ])
    mocks.store.currentDocument = null
    mocks.store.documentDetailLoading = false
    mocks.store.fetchKnowledgeBases.mockResolvedValue(undefined)
    mocks.store.selectKnowledgeBase.mockResolvedValue(undefined)
    mocks.store.fetchDocumentDetail.mockResolvedValue(undefined)
    mocks.store.createDocument.mockResolvedValue(null)
    mocks.store.updateDocument.mockResolvedValue(undefined)
    mocks.store.deleteDocument.mockResolvedValue(undefined)
    mocks.store.updateKnowledgeBase.mockResolvedValue(undefined)
    mocks.store.deleteKnowledgeBase.mockResolvedValue(undefined)
  })

  afterEach(() => {
    unmount?.()
    unmount = undefined
  })

  it('filters collections and documents, sorts results, and handles empty search results', async () => {
    await mountPage()

    page.knowledgeBaseSearch.value = '  BETA '
    expect(page.filteredKnowledgeBases.value.map(kb => kb.id)).toEqual(['kb-2'])

    page.knowledgeBaseSearch.value = ''
    page.documentSearch.value = 'earnings'
    expect(page.sortedDocuments.value.map(doc => doc.id)).toEqual(['doc-2'])

    page.documentSearch.value = 'no match'
    expect(page.sortedDocuments.value).toEqual([])
    expect(page.displayRows.value).toEqual([])
    expect(page.selectedDocument.value).toBeNull()
  })

  it('creates a folder, imports a document into it, and removes a selected document', async () => {
    await mountPage()
    const folder = makeDocument({ id: 'folder-1', title: 'Research', content: '', is_folder: true })
    const imported = makeDocument({ id: 'imported-1', title: 'Imported brief', content: 'Imported content' })
    mocks.store.createDocument
      .mockImplementationOnce(async () => {
        mocks.store.documents.push(folder)
        return folder
      })
      .mockImplementationOnce(async () => {
        mocks.store.documents.push(imported)
        return imported
      })
    mocks.store.deleteDocument.mockImplementation(async (id: string) => {
      const index = mocks.store.documents.findIndex(document => (document as KBDocumentItem).id === id)
      if (index >= 0) mocks.store.documents.splice(index, 1)
    })

    page.openCreateDialog(true, null)
    page.createDialog.title = '  Research  '
    await page.submitCreateDialog()

    expect(mocks.store.createDocument).toHaveBeenNthCalledWith(1, {
      title: 'Research',
      content: '',
      content_type: 'markdown',
      is_folder: true,
      parent_id: null,
    })
    expect(page.selectedDocumentId.value).toBe('folder-1')
    expect(page.expandedFolderIds.value.has('folder-1')).toBe(true)
    expect(page.createDialog.open).toBe(false)

    page.openImportDialog()
    page.importDialog.title = ' Imported brief '
    page.importDialog.content = 'Imported content'
    await page.submitImportDialog()

    expect(mocks.store.createDocument).toHaveBeenNthCalledWith(2, {
      title: 'Imported brief',
      content: 'Imported content',
      content_type: 'markdown',
      is_folder: false,
      parent_id: 'folder-1',
    })
    expect(page.selectedDocumentId.value).toBe('imported-1')

    page.selectedDocumentIds.value.add('imported-1')
    page.openDeleteDialog(imported)
    await page.submitDeleteDialog()

    expect(mocks.store.deleteDocument).toHaveBeenCalledWith('imported-1')
    expect(page.selectedDocumentIds.value.has('imported-1')).toBe(false)
    expect(page.deleteDialog.open).toBe(false)
  })

  it('does not create a document without a selected collection', async () => {
    mocks.store.currentKnowledgeBase = null
    await mountPage()

    page.openCreateDialog(false)
    page.createDialog.title = 'Will not be created'
    await page.submitCreateDialog()
    expect(mocks.store.createDocument).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalled()
  })

  it('clears stale detail when loading the selected document fails', async () => {
    mocks.store.fetchDocumentDetail.mockRejectedValueOnce(new Error('document request failed'))
    await mountPage()
    page.selectedDocumentId.value = 'doc-2'
    await flushPromises()

    expect(mocks.store.clearCurrentDocument).toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalled()
  })

  it('sorts by the selected field and toggles folder expansion while keeping selection in sync', async () => {
    const folder = makeDocument({ id: 'folder-1', title: 'Research', is_folder: true, content: '' })
    const later = makeDocument({
      id: 'doc-later',
      title: 'Zebra report',
      parent_id: 'folder-1',
      status: 'published',
      sort_order: 0,
      updated_at: '2026-05-01T00:00:00Z',
      file_path: 'reports/zebra.md',
    })
    const earlier = makeDocument({
      id: 'doc-earlier',
      title: 'Alpha report',
      parent_id: 'folder-1',
      status: 'draft',
      sort_order: 1,
      updated_at: '2026-04-01T00:00:00Z',
    })
    mocks.store.documents = reactive([folder, later, earlier])
    await mountPage()

    expect(page.displayRows.value.map(row => row.id)).toEqual(['folder-1', 'doc-later', 'doc-earlier'])
    expect(page.displayRows.value.find(row => row.id === 'doc-later')?.depth).toBe(1)
    page.toggleFolder('folder-1')
    expect(page.expandedFolderIds.value.has('folder-1')).toBe(false)
    expect(page.displayRows.value.map(row => row.id)).toEqual(['folder-1'])
    page.toggleFolder('folder-1')
    expect(page.displayRows.value.find(row => row.id === 'doc-later')?.depth).toBe(1)

    page.sortKey.value = 'title'
    expect(page.sortedDocuments.value.map(document => document.id)).toEqual(['doc-earlier', 'folder-1', 'doc-later'])
    page.sortKey.value = 'updated_at'
    expect(page.sortedDocuments.value.map(document => document.id)).toEqual(['doc-later', 'folder-1', 'doc-earlier'])
    page.sortKey.value = 'status'
    expect(page.sortedDocuments.value.map(document => document.id)).toEqual(['folder-1', 'doc-earlier', 'doc-later'])

    page.documentSearch.value = 'reports/zebra'
    expect(page.sortedDocuments.value.map(document => document.id)).toEqual(['doc-later'])
    page.documentSearch.value = ''
    page.toggleSelectAllVisible({ target: { checked: true } } as unknown as Event)
    expect(page.allVisibleSelected.value).toBe(true)
    expect([...page.selectedDocumentIds.value]).toEqual(expect.arrayContaining(['folder-1', 'doc-later', 'doc-earlier']))
    page.toggleSelectAllVisible({ target: { checked: false } } as unknown as Event)
    expect(page.selectedDocumentIds.value.size).toBe(0)
  })

  it('hides every descendant of a collapsed ancestor and reveals nested children on expansion', async () => {
    mocks.store.documents = reactive([
      makeDocument({ id: 'root-folder', title: 'Root folder', is_folder: true, content: '' }),
      makeDocument({
        id: 'nested-folder',
        title: 'Nested folder',
        is_folder: true,
        content: '',
        parent_id: 'root-folder',
      }),
      makeDocument({ id: 'nested-doc', title: 'Nested document', parent_id: 'nested-folder' }),
    ])
    await mountPage()

    expect(page.displayRows.value.map(row => [row.id, row.depth])).toEqual([
      ['root-folder', 0],
      ['nested-folder', 1],
    ])

    page.toggleFolder('root-folder')
    expect(page.displayRows.value.map(row => row.id)).toEqual(['root-folder'])
    page.toggleFolder('root-folder')
    page.toggleFolder('nested-folder')

    expect(page.displayRows.value.map(row => [row.id, row.depth])).toEqual([
      ['root-folder', 0],
      ['nested-folder', 1],
      ['nested-doc', 2],
    ])
  })

  it('keeps matching documents visible when their parent is absent or filtered out', async () => {
    mocks.store.documents = reactive([
      makeDocument({ id: 'unmatched-folder', title: 'Other research', is_folder: true, content: '' }),
      makeDocument({ id: 'filtered-child', title: 'Needle result', parent_id: 'unmatched-folder' }),
      makeDocument({ id: 'orphan', title: 'Needle orphan', parent_id: 'missing-folder' }),
    ])
    await mountPage()
    page.documentSearch.value = 'needle'

    expect(page.sortedDocuments.value.map(document => document.id)).toEqual(['filtered-child', 'orphan'])
    expect(page.displayRows.value.map(row => [row.id, row.depth])).toEqual([
      ['filtered-child', 0],
      ['orphan', 0],
    ])
  })

  it('renders cyclic document relationships once and returns safely', async () => {
    mocks.store.documents = reactive([
      makeDocument({ id: 'cycle-a', title: 'Cycle A', parent_id: 'cycle-b' }),
      makeDocument({ id: 'cycle-b', title: 'Cycle B', parent_id: 'cycle-a' }),
    ])
    await mountPage()

    expect(page.displayRows.value.map(row => row.id)).toEqual(['cycle-a', 'cycle-b'])
    expect(new Set(page.displayRows.value.map(row => row.id)).size).toBe(2)
  })

  it.each([
    ['publish', { status: 'published' }],
    ['draft', { status: 'draft' }],
    ['move_root', { parent_id: null }],
    ['mark_not_indexed', { index_status: 'not_indexed' }],
  ] as const)('applies bulk %s to the selected documents', async (mode, patch) => {
    await mountPage()
    page.selectedDocumentIds.value = new Set(['doc-1', 'doc-2'])

    page.openBulkActionDialog(mode)
    expect(page.bulkDialog.open).toBe(true)
    await page.submitBulkDialog()

    expect(mocks.store.updateDocument).toHaveBeenNthCalledWith(1, 'doc-1', patch)
    expect(mocks.store.updateDocument).toHaveBeenNthCalledWith(2, 'doc-2', patch)
    expect(page.bulkDialog.open).toBe(false)
    expect(page.selectedDocumentIds.value.size).toBe(2)
  })

  it('deletes all selected documents as a bulk action and guards empty selection', async () => {
    await mountPage()

    page.openBulkActionDialog('delete')
    expect(page.bulkDialog.open).toBe(false)
    expect(ElMessage.warning).toHaveBeenCalled()
    await page.submitBulkDialog()
    expect(mocks.store.deleteDocument).not.toHaveBeenCalled()

    page.selectedDocumentIds.value = new Set(['doc-1', 'doc-2'])
    page.openBulkActionDialog('delete')
    await page.submitBulkDialog()

    expect(mocks.store.deleteDocument).toHaveBeenNthCalledWith(1, 'doc-1')
    expect(mocks.store.deleteDocument).toHaveBeenNthCalledWith(2, 'doc-2')
    expect(page.selectedDocumentIds.value.size).toBe(0)
    expect(page.bulkDialog.open).toBe(false)
  })

  it('persists retrieval settings with supported boundary values and a trimmed prompt suffix', async () => {
    await mountPage()
    page.openKnowledgeBaseSettingsDialog()
    page.knowledgeBaseSettingsDialog.form.default_top_k = 20
    page.knowledgeBaseSettingsDialog.form.min_similarity = 1
    page.knowledgeBaseSettingsDialog.form.max_context_chunks = 12
    page.knowledgeBaseSettingsDialog.form.conversation_lookback_messages = 20
    page.knowledgeBaseSettingsDialog.form.system_prompt_suffix = '  Use earnings reports first.  '

    await page.submitKnowledgeBaseSettingsDialog()

    expect(mocks.store.updateKnowledgeBase).toHaveBeenCalledWith('kb-1', {
      settings: expect.objectContaining({
        default_top_k: 20,
        min_similarity: 1,
        max_context_chunks: 12,
        conversation_lookback_messages: 20,
        system_prompt_suffix: 'Use earnings reports first.',
      }),
    })
    expect(page.knowledgeBaseSettingsDialog.open).toBe(false)
  })

  it('selects a collection, resets document controls, and opens its requested route document', async () => {
    mocks.routeQuery = { kbId: 'kb-2', docId: 'doc-2' }
    mocks.store.documents = reactive([
      makeDocument({ id: 'folder-2', knowledge_base_id: 'kb-2', is_folder: true, content: '' }),
      makeDocument({ id: 'doc-2', knowledge_base_id: 'kb-2', parent_id: 'folder-2' }),
    ])
    await mountPage()
    page.documentSearch.value = 'old filter'
    page.selectedDocumentIds.value = new Set(['doc-2'])
    page.currentPage.value = 3

    await page.handleSelectKnowledgeBase('kb-2')

    expect(mocks.store.selectKnowledgeBase).toHaveBeenLastCalledWith('kb-2')
    expect(page.documentSearch.value).toBe('')
    expect(page.selectedDocumentIds.value.size).toBe(0)
    expect(page.currentPage.value).toBe(1)
    expect(page.expandedFolderIds.value.has('folder-2')).toBe(true)
    expect(page.selectedDocumentId.value).toBe('doc-2')
  })
})
