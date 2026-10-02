'use client'

import Markdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getFileDownloadUrl } from '@/lib/api/files'

function repositoryPath(value: string): string | null {
  const parts: string[] = []
  try {
    for (const part of decodeURIComponent(value).split('/')) {
      if (!part || part === '.') continue
      if (part === '..') {
        if (!parts.length) return null
        parts.pop()
      } else {
        if (
          part.includes('\\') ||
          [...part].some((character) => character.charCodeAt(0) < 32)
        )
          return null
        parts.push(part)
      }
    }
  } catch {
    return null
  }
  return parts.join('/')
}

interface MarkdownTreeNode {
  type: string
  value?: string
  alt?: string | null
  children?: MarkdownTreeNode[]
  data?: { hProperties?: Record<string, unknown> }
}

function headingText(node: MarkdownTreeNode): string {
  if (node.value != null) return node.type === 'html' ? '' : node.value
  if (node.type === 'image') return node.alt || ''
  if (node.children) return node.children.map(headingText).join('')
  return ''
}

// Keep in-document README links usable without accepting IDs from raw HTML.
function remarkHeadingIds() {
  return (tree: MarkdownTreeNode) => {
    const used = new Map<string, number>()
    for (const node of tree.children || []) {
      if (node.type !== 'heading') continue
      const base = headingText(node)
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\s_-]/gu, '')
        .replace(/\s/g, '-')
      const count = used.get(base) || 0
      used.set(base, count + 1)
      node.data = {
        ...node.data,
        hProperties: {
          ...node.data?.hProperties,
          id: count ? `${base}-${count}` : base,
        },
      }
    }
  }
}

export function resolveReadmeUrl(
  value: string,
  projectId: string,
  image: boolean,
): string | undefined {
  if (!value || value.startsWith('//')) return undefined
  if (value.startsWith('#')) return image ? undefined : value
  if (/^[a-z][a-z\d+.-]*:/i.test(value)) {
    const safe = defaultUrlTransform(value)
    if (!safe || !/^(https?:|mailto:)/i.test(safe)) return undefined
    if (image && !/^https?:/i.test(safe)) return undefined
    return safe
  }
  const repositoryUrl = value.split(/[?#]/)[0]
  const path = repositoryPath(repositoryUrl)
  if (path == null) return undefined
  const directory = !image && /\/$|%2f$/i.test(repositoryUrl)
  if (!path && !directory) return undefined
  return image
    ? getFileDownloadUrl({ kind: 'project', projectId }, path)
    : `/projects/${encodeURIComponent(projectId)}/files?${directory ? 'directory' : 'path'}=${encodeURIComponent(path)}`
}

export function ProjectReadmeMarkdown({
  projectId,
  content,
}: {
  projectId: string
  content: string
}) {
  return (
    <div className="min-w-0 break-words text-sm leading-relaxed text-slate-300 [&_h1]:mb-4 [&_h1]:text-2xl [&_h1]:font-semibold [&_h2]:mb-3 [&_h2]:mt-6 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:text-lg [&_h3]:font-semibold [&_p]:my-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-1 [&_a]:text-phosphor-300 [&_a]:underline [&_a]:underline-offset-2 [&_a:focus-visible]:outline [&_a:focus-visible]:outline-2 [&_a:focus-visible]:outline-phosphor-400 [&_pre]:my-4 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:border [&_pre]:border-slate-800 [&_pre]:bg-slate-950 [&_pre]:p-4 [&_code]:font-mono [&_code]:text-xs [&_code]:text-amber-200 [&_blockquote]:border-l-2 [&_blockquote]:border-slate-700 [&_blockquote]:pl-4 [&_blockquote]:text-slate-400 [&_img]:max-w-full [&_img]:rounded [&_hr]:my-5 [&_hr]:border-slate-800 [&_th]:border [&_th]:border-slate-700 [&_th]:bg-slate-800/60 [&_th]:p-2 [&_th]:text-left [&_td]:border [&_td]:border-slate-800 [&_td]:p-2">
      <Markdown
        skipHtml
        remarkPlugins={[remarkGfm, remarkHeadingIds]}
        urlTransform={(url, key) =>
          resolveReadmeUrl(url, projectId, key === 'src')
        }
        components={{
          a: ({ node: _node, ...props }) => (
            <a {...props} rel="noreferrer noopener" />
          ),
          img: ({ node: _node, src, alt, ...props }) => {
            if (!src) return <span>{alt}</span>
            return (
              // biome-ignore lint/performance/noImgElement: README images have unknown dimensions and use the existing file download endpoint.
              <img {...props} src={src} alt={alt || ''} loading="lazy" />
            )
          },
          table: ({ node: _node, ...props }) => (
            <div className="my-4 overflow-x-auto">
              <table {...props} className="w-full border-collapse text-xs" />
            </div>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  )
}
