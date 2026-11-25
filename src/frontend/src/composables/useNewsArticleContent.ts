import { ref } from 'vue'

import { marketIntelApi } from '@/api/marketIntel'

interface ArticleIdentity {
  id?: string | null
  headline: string
}

export function useNewsArticleContent() {
  const visible = ref(false)
  const loading = ref(false)
  const content = ref('')
  const title = ref('')
  let generation = 0
  let activeArticleId = ''
  let unmounted = false

  async function show(article: ArticleIdentity) {
    if (!article.id || unmounted) return
    const requestGeneration = ++generation
    activeArticleId = article.id
    visible.value = true
    loading.value = true
    content.value = ''
    title.value = article.headline
    try {
      const response = await marketIntelApi.getArticleContent(article.id)
      if (
        requestGeneration !== generation
        || activeArticleId !== article.id
        || !visible.value
        || unmounted
      ) return
      content.value = response.content || response.summary || ''
    } finally {
      if (requestGeneration === generation) loading.value = false
    }
  }

  function close() {
    generation++
    activeArticleId = ''
    visible.value = false
    loading.value = false
    content.value = ''
    title.value = ''
  }

  function dispose() {
    unmounted = true
    generation++
    activeArticleId = ''
  }

  return {
    articleContentVisible: visible,
    articleContentLoading: loading,
    articleContent: content,
    articleContentTitle: title,
    showArticleContent: show,
    closeArticleContent: close,
    disposeArticleContent: dispose,
  }
}
