import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import MonacoEditor from '@/components/common/MonacoEditor.vue'

const mountedWrappers: ReturnType<typeof mount>[] = []
type MonacoEditorProps = {
  modelValue: string
  language?: string
  height?: number
  readOnly?: boolean
  theme?: string
}

// Mock the lazy module so rejection, retry, and loading can be controlled.
const monacoMocks = vi.hoisted(() => {
  const editor = {
    getValue: vi.fn(() => ''),
    setValue: vi.fn(),
    dispose: vi.fn(),
    onDidChangeModelContent: vi.fn(),
    updateOptions: vi.fn(),
  }
  const module = {
    editor: {
      create: vi.fn(() => editor),
      setTheme: vi.fn(),
    },
  }
  return { editor, module, loadModule: vi.fn() }
})

vi.mock('@/components/common/loadMonacoEditor', () => ({
  loadMonacoEditor: monacoMocks.loadModule,
}))

describe('MonacoEditor', () => {
  function mountEditor(props: MonacoEditorProps) {
    const wrapper = mount(MonacoEditor, { props })
    mountedWrappers.push(wrapper)
    return wrapper
  }

  async function mountEditorAndWait(props: MonacoEditorProps) {
    const wrapper = mountEditor(props)
    await flushPromises()
    return wrapper
  }

  beforeEach(() => {
    vi.clearAllMocks()
    monacoMocks.loadModule.mockReset()
    monacoMocks.loadModule.mockResolvedValue(monacoMocks.module)
  })

  afterEach(() => {
    for (const wrapper of mountedWrappers.splice(0)) wrapper.unmount()
    vi.restoreAllMocks()
  })

  it('shows loading and a retryable error when the dynamic import rejects', async () => {
    let rejectLoad!: (error: Error) => void
    monacoMocks.loadModule
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectLoad = reject }))
      .mockResolvedValueOnce(monacoMocks.module)

    const wrapper = mountEditor({ modelValue: 'print("hello")' })
    await nextTick()
    expect(wrapper.get('[role="status"]').text()).toContain('加载中')

    rejectLoad(new Error('chunk unavailable'))
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('操作失败')
    expect(wrapper.get('button').text()).toBe('重试')
    expect(monacoMocks.module.editor.create).not.toHaveBeenCalled()

    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(monacoMocks.loadModule).toHaveBeenCalledTimes(2)
    expect(monacoMocks.module.editor.create).toHaveBeenCalledOnce()
  })

  it('should render the container before loading Monaco', async () => {
    const wrapper = mountEditor({ modelValue: 'print("hello")' })
    expect(wrapper.find('.monaco-editor-container').exists()).toBe(true)
    expect(monacoMocks.editor.onDidChangeModelContent).not.toHaveBeenCalled()
    await flushPromises()
    expect(monacoMocks.editor.onDidChangeModelContent).toHaveBeenCalled()
  })

  it('should use default height', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '' })
    const container = wrapper.find('.monaco-editor-shell')
    expect(container.attributes('style')).toContain('height: 400px')
  })

  it('should use custom height', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '', height: 600 })
    const container = wrapper.find('.monaco-editor-shell')
    expect(container.attributes('style')).toContain('height: 600px')
  })

  it('should use default language as python', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '' })
    expect(wrapper.props('language')).toBe('python')
  })

  it('should accept custom language', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '', language: 'javascript' })
    expect(wrapper.props('language')).toBe('javascript')
  })

  it('should use default theme', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '' })
    expect(wrapper.props('theme')).toBe('vs')
  })

  it('should accept custom theme', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '', theme: 'vs-dark' })
    expect(wrapper.props('theme')).toBe('vs-dark')
  })

  it('should be editable by default', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '' })
    expect(wrapper.props('readOnly')).toBe(false)
  })

  it('should accept readOnly prop', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: '', readOnly: true })
    expect(wrapper.props('readOnly')).toBe(true)
  })

  it('should emit update:modelValue on content change', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: 'initial code' })

    // The onDidChangeModelContent callback should be registered
    expect(monacoMocks.editor.onDidChangeModelContent).toHaveBeenCalled()

    // Simulate content change by getting the callback
    const changeCallback = monacoMocks.editor.onDidChangeModelContent.mock.calls[0]?.[0]
    if (changeCallback) {
      monacoMocks.editor.getValue.mockReturnValue('new code')
      changeCallback()

      // Check if v-model update was triggered
      expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    }
  })

  it('syncs model and theme changes and disposes the editor', async () => {
    const wrapper = await mountEditorAndWait({ modelValue: 'initial code' })
    await wrapper.setProps({ modelValue: 'updated code', theme: 'vs-dark' })

    expect(monacoMocks.editor.setValue).toHaveBeenCalledWith('updated code')
    expect(monacoMocks.module.editor.setTheme).toHaveBeenCalledWith('vs-dark')

    wrapper.unmount()
    expect(monacoMocks.editor.dispose).toHaveBeenCalledOnce()
  })
})
