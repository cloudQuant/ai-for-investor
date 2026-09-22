<template>
  <div
    class="monaco-editor-shell"
    :style="{ height: height + 'px' }"
    :aria-busy="loading"
  >
    <div
      ref="editorRef"
      class="monaco-editor-container"
    />
    <div
      v-if="loading"
      class="monaco-editor-state"
      role="status"
      aria-live="polite"
    >
      {{ t('common.loading') }}
    </div>
    <div
      v-else-if="loadError"
      class="monaco-editor-state monaco-editor-state--error"
      role="alert"
    >
      <span>{{ t('common.failed') }}</span>
      <button
        type="button"
        class="monaco-editor-retry"
        @click="initializeEditor"
      >
        {{ t('commonUi.errorRetry') }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type * as monaco from 'monaco-editor'
import { useI18n } from 'vue-i18n'
import { useAsyncModule } from '@/composables/useAsyncModule'
import { loadMonacoEditor } from '@/components/common/loadMonacoEditor'

interface Props {
  modelValue: string
  language?: string
  height?: number
  readOnly?: boolean
  theme?: string
}

const props = withDefaults(defineProps<Props>(), {
  language: 'python',
  height: 400,
  readOnly: false,
  theme: 'vs',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const { t } = useI18n()
const editorRef = ref<HTMLDivElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null
let disposed = false
const {
  value: monacoApi,
  loading,
  error: loadError,
  load: loadMonaco,
} = useAsyncModule(() => loadMonacoEditor())

async function initializeEditor() {
  await loadMonaco()
  if (disposed || !editorRef.value || !monacoApi.value || editor) return

  editor = monacoApi.value.editor.create(editorRef.value, {
    value: props.modelValue,
    language: props.language,
    theme: props.theme,
    readOnly: props.readOnly,
    minimap: { enabled: false },
    fontSize: 14,
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    automaticLayout: true,
    tabSize: 4,
    wordWrap: 'on',
  })

  editor.onDidChangeModelContent(() => {
    const value = editor?.getValue() || ''
    emit('update:modelValue', value)
  })
}

onMounted(() => {
  void initializeEditor()
})

watch(() => props.modelValue, (newVal) => {
  if (editor && editor.getValue() !== newVal) {
    editor.setValue(newVal)
  }
})

watch(() => props.theme, (newTheme) => {
  monacoApi.value?.editor.setTheme(newTheme)
})

onUnmounted(() => {
  disposed = true
  editor?.dispose()
  editor = null
})
</script>

<style scoped>
.monaco-editor-shell {
  position: relative;
  width: 100%;
}

.monaco-editor-container {
  width: 100%;
  height: 100%;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  overflow: hidden;
}

.monaco-editor-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-color);
}

.monaco-editor-retry {
  border: 0;
  padding: 0;
  color: var(--el-color-primary);
  background: transparent;
  cursor: pointer;
}
</style>
