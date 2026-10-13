import DOMPurify from 'dompurify'
import { marked } from 'marked'

/**
 * Allowed HTML tags for Markdown rendering.
 * Restricted to safe formatting tags only — no script, iframe, object, embed, or form.
 */
const ALLOWED_TAGS = [
  'p', 'br', 'hr',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'ul', 'ol', 'li',
  'table', 'thead', 'tbody', 'tr', 'th', 'td',
  'pre', 'code', 'blockquote',
  'strong', 'em', 'del', 's', 'mark', 'sub', 'sup',
  'a', 'img',
  'span', 'div',
]

/**
 * Allowed HTML attributes for sanitized output.
 * Only safe attributes needed for Markdown rendering are permitted.
 */
const ALLOWED_ATTR = ['href', 'src', 'alt', 'class', 'id', 'title', 'target', 'rel']

const DANGEROUS_REMOTE_TAG_RE =
  /<(script|iframe|object|embed)\b[\s\S]*?<\/\1>|<(script|iframe|object|embed)\b[^>]*\/?>/gi
const EVENT_HANDLER_ATTR_RE = /\s+on[a-z]+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi
const UNSAFE_URI_ATTR_RE =
  /\s+(href|src)\s*=\s*(?:"\s*(?:javascript|data):[^"]*"|'\s*(?:javascript|data):[^']*'|\s*(?:javascript|data):[^\s>]+)/gi
const SCRIPT_PROTOCOL_RE = /javascript\s*:/gi

export interface SanitizeOptions {
  /** Allow <img> tags in output. Defaults to true. */
  allowImages?: boolean
  /** Allow <a> tags in output. Defaults to true. */
  allowLinks?: boolean
}

/**
 * Render raw Markdown to sanitized HTML.
 *
 * Converts Markdown to HTML using `marked`, then sanitizes the output
 * with DOMPurify using an explicit whitelist of allowed tags and attributes.
 *
 * @param raw - Raw Markdown string. Returns empty string for null/undefined.
 * @param options - Optional configuration to restrict images or links.
 * @returns Sanitized HTML string safe for insertion via v-html.
 */
export function renderMarkdown(raw: string | null | undefined, options?: SanitizeOptions): string {
  if (raw == null || raw === '') {
    return ''
  }

  // Convert Markdown to HTML
  const html = marked.parse(raw, { async: false }) as string

  // Build tag whitelist based on options
  const disallowedTags = new Set<string>()
  if (options?.allowImages === false) {
    disallowedTags.add('img')
  }
  if (options?.allowLinks === false) {
    disallowedTags.add('a')
  }
  const tags = ALLOWED_TAGS.filter(tag => !disallowedTags.has(tag))

  // Build attribute whitelist based on options
  const disallowedAttrs = new Set<string>()
  if (options?.allowImages === false) {
    disallowedAttrs.add('src')
    disallowedAttrs.add('alt')
  }
  if (options?.allowLinks === false) {
    disallowedAttrs.add('href')
    disallowedAttrs.add('target')
    disallowedAttrs.add('rel')
  }
  const attrs = ALLOWED_ATTR.filter(attr => !disallowedAttrs.has(attr))

  const precleaned = html
    .replace(DANGEROUS_REMOTE_TAG_RE, '')
    .replace(UNSAFE_URI_ATTR_RE, '')
    .replace(EVENT_HANDLER_ATTR_RE, '')
    .replace(SCRIPT_PROTOCOL_RE, '')

  // Sanitize HTML with DOMPurify
  const clean = DOMPurify.sanitize(precleaned, {
    ALLOWED_TAGS: tags,
    ALLOWED_ATTR: attrs,
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
  })

  return clean
    .replace(UNSAFE_URI_ATTR_RE, '')
    .replace(EVENT_HANDLER_ATTR_RE, '')
    .replace(SCRIPT_PROTOCOL_RE, '')
}
