/**
 * Language extension loader for CodeMirror.
 *
 * Maps backend language strings to CodeMirror extensions.
 * Uses dynamic imports for bundle splitting.
 */

import type { Extension } from '@codemirror/state'

type LanguageLoader = () => Promise<Extension>

const loaders: Record<string, LanguageLoader> = {
  javascript: async () => {
    const { javascript } = await import('@codemirror/lang-javascript')
    return javascript({ jsx: true, typescript: false })
  },
  typescript: async () => {
    const { javascript } = await import('@codemirror/lang-javascript')
    return javascript({ jsx: true, typescript: true })
  },
  python: async () => {
    const { python } = await import('@codemirror/lang-python')
    return python()
  },
  json: async () => {
    const { json } = await import('@codemirror/lang-json')
    return json()
  },
  html: async () => {
    const { html } = await import('@codemirror/lang-html')
    return html()
  },
  css: async () => {
    const { css } = await import('@codemirror/lang-css')
    return css()
  },
  markdown: async () => {
    const { markdown } = await import('@codemirror/lang-markdown')
    return markdown()
  },
  yaml: async () => {
    const { yaml } = await import('@codemirror/lang-yaml')
    return yaml()
  },
  sql: async () => {
    const { sql } = await import('@codemirror/lang-sql')
    return sql()
  },
  rust: async () => {
    const { rust } = await import('@codemirror/lang-rust')
    return rust()
  },
  go: async () => {
    const { go } = await import('@codemirror/lang-go')
    return go()
  },
  java: async () => {
    const { java } = await import('@codemirror/lang-java')
    return java()
  },
  cpp: async () => {
    const { cpp } = await import('@codemirror/lang-cpp')
    return cpp()
  },
  xml: async () => {
    const { xml } = await import('@codemirror/lang-xml')
    return xml()
  },
  php: async () => {
    const { php } = await import('@codemirror/lang-php')
    return php()
  },
}

export async function loadLanguageExtension(
  language: string | null,
): Promise<Extension | null> {
  if (!language) return null
  const loader = loaders[language]
  if (!loader) return null
  try {
    return await loader()
  } catch {
    return null
  }
}
