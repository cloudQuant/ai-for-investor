import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import KnowledgeBaseDocumentPage from '@/views/KnowledgeBaseDocumentPage.vue'
import { knowledgeBaseApi } from '@/api/knowledgeBase'
import { elStubs } from '@/test/stubs'

const routeMocks = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  params: { kbId: 'kb-1', docId: 'doc-1' } as Record<string, string>,
  query: {} as Record<string, unknown>,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routeMocks.push, replace: routeMocks.replace }),
  useRoute: () => ({ params: routeMocks.params, query: routeMocks.query }),
}))

vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api')
  return actual
})

vi.mock('@/api/knowledgeBase', () => ({
  knowledgeBaseApi: {
    getDocument: vi.fn().mockResolvedValue({
      id: 'doc-1',
      knowledge_base_id: 'kb-1',
      title: '文档1',
      content: '这是正文内容',
      content_type: 'markdown',
      file_path: null,
      is_folder: false,
      parent_id: null,
      sort_order: 0,
      status: 'draft',
      index_status: 'not_indexed',
      indexed_at: null,
      metadata: {
        reqdocs_source_filename: '文档1.pdf',
        reqdocs_source_mime_type: 'application/pdf',
      },
      created_at: '2026-04-23T00:00:00Z',
      updated_at: '2026-04-23T00:00:00Z',
    }),
    getDocumentSourceFile: vi.fn().mockResolvedValue(new Blob(['pdf-bytes'], { type: 'application/pdf' })),
  },
}))

describe('KnowledgeBaseDocumentPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMocks.params = { kbId: 'kb-1', docId: 'doc-1' }
    routeMocks.query = {}
  })

  it('loads document and shows tabs with source file available', async () => {
    const wrapper = mount(KnowledgeBaseDocumentPage, { global: { stubs: { ...elStubs } } })
    await flushPromises()

    expect(wrapper.text()).toContain('文档1')
    expect(wrapper.text()).toContain('源文件')
    expect(wrapper.text()).toContain('Markdown')
    expect(wrapper.text()).toContain('文档摘要')
    expect(wrapper.text()).toContain('阅读建议')
    expect(wrapper.text()).toContain('文档1.pdf')
    expect(wrapper.text()).toContain('快捷 AI 问答')
  })

  it('reports missing route identifiers without requesting a document', async () => {
    routeMocks.params = {}
    const wrapper = mount(KnowledgeBaseDocumentPage, { global: { stubs: { ...elStubs } } })
    await flushPromises()

    expect(wrapper.get('[data-test="kb-doc-error"]').text()).toContain('缺少')
    expect(knowledgeBaseApi.getDocument).not.toHaveBeenCalled()
  })

  it('shows the document request error and routes quick questions with the current collection', async () => {
    vi.mocked(knowledgeBaseApi.getDocument).mockRejectedValueOnce(new Error('document service unavailable'))
    const failedWrapper = mount(KnowledgeBaseDocumentPage, { global: { stubs: { ...elStubs } } })
    await flushPromises()
    expect(failedWrapper.get('[data-test="kb-doc-error"]').text()).toContain('document service unavailable')
    failedWrapper.unmount()

    const wrapper = mount(KnowledgeBaseDocumentPage, { global: { stubs: { ...elStubs } } })
    await flushPromises()
    await wrapper.get('.kb-doc-button-primary').trigger('click')

    expect(routeMocks.push).toHaveBeenCalledWith({
      path: '/ai/chat',
      query: { kbId: 'kb-1', prompt: expect.any(String) },
    })
  })

  it('renders the real document Q&A prompts and routes a selected prompt to chat', async () => {
    const wrapper = mount(KnowledgeBaseDocumentPage, { global: { stubs: { ...elStubs } } })
    await flushPromises()

    const prompts = wrapper.findAll('.kb-doc-prompt-button')
    expect(prompts).toHaveLength(3)
    const prompt = prompts[1].text()
    await prompts[1].trigger('click')

    expect(routeMocks.push).toHaveBeenCalledWith({
      path: '/ai/chat',
      query: { kbId: 'kb-1', prompt },
    })
  })

  it('opens the document context drawer and restores focus after closing it', async () => {
    const wrapper = mount(KnowledgeBaseDocumentPage, {
      attachTo: document.body,
      global: { stubs: { ...elStubs, KnowledgeBaseDocSourceView: true } },
    })
    await flushPromises()
    const trigger = wrapper.get('[data-test="kb-doc-open-side-panel"]')
    await trigger.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.kb-doc-side--mobile-open').attributes('role')).toBe('dialog')
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭文档上下文')

    await wrapper.find('.kb-doc-mobile-side-close').trigger('click')
    await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })

  it('closes the document context drawer with Escape', async () => {
    const wrapper = mount(KnowledgeBaseDocumentPage, {
      attachTo: document.body,
      global: { stubs: { ...elStubs, KnowledgeBaseDocSourceView: true } },
    })
    await flushPromises()
    await wrapper.get('[data-test="kb-doc-open-side-panel"]').trigger('click')
    await wrapper.find('.kb-doc-side').trigger('keydown', { key: 'Escape' })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.kb-doc-side--mobile-open').exists()).toBe(false)
    wrapper.unmount()
  })

})
