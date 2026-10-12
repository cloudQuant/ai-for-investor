import type { NewsArticleItem } from '@/api/marketIntel'

export function formatNewsArticleMeta(article: NewsArticleItem, unknownSource: string): string {
  const parts = [article.source || unknownSource, ...(article.tickers ?? [])].filter(Boolean)
  return parts.join(' · ')
}
