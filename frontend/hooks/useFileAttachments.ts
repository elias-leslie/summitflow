'use client'

import {
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useState,
} from 'react'

export interface FileAttachment {
  id: string
  file: File
  previewUrl?: string
  type: 'image' | 'document' | 'other'
}

function getFileType(file: File): 'image' | 'document' | 'other' {
  if (file.type.startsWith('image/')) return 'image'
  if (
    file.type.includes('pdf') ||
    file.type.includes('text') ||
    file.type.includes('document') ||
    file.name.endsWith('.md') ||
    file.name.endsWith('.txt') ||
    file.name.endsWith('.json')
  )
    return 'document'
  return 'other'
}

export interface UseFileAttachmentsReturn {
  attachments: FileAttachment[]
  isDragging: boolean
  addFiles: (files: FileList | File[]) => void
  removeAttachment: (id: string) => void
  clearAttachments: () => void
  handleDragOver: (e: DragEvent) => void
  handleDragLeave: (e: DragEvent) => void
  handleDrop: (e: DragEvent) => void
  handlePaste: (e: ClipboardEvent) => void
  handleFileChange: (e: ChangeEvent<HTMLInputElement>) => void
}

export function useFileAttachments(): UseFileAttachmentsReturn {
  const [attachments, setAttachments] = useState<FileAttachment[]>([])
  const [isDragging, setIsDragging] = useState(false)

  // Cleanup preview URLs on unmount or attachment change
  useEffect(() => {
    return () => {
      attachments.forEach((att) => {
        if (att.previewUrl) {
          URL.revokeObjectURL(att.previewUrl)
        }
      })
    }
  }, [attachments])

  const addFiles = useCallback((files: FileList | File[]) => {
    const newAttachments: FileAttachment[] = Array.from(files).map((file) => {
      const type = getFileType(file)
      const previewUrl =
        type === 'image' ? URL.createObjectURL(file) : undefined
      return {
        id: crypto.randomUUID(),
        file,
        type,
        previewUrl,
      }
    })
    setAttachments((prev) => [...prev, ...newAttachments])
  }, [])

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const att = prev.find((a) => a.id === id)
      if (att?.previewUrl) {
        URL.revokeObjectURL(att.previewUrl)
      }
      return prev.filter((a) => a.id !== id)
    })
  }, [])

  const clearAttachments = useCallback(() => {
    setAttachments((prev) => {
      prev.forEach((att) => {
        if (att.previewUrl) {
          URL.revokeObjectURL(att.previewUrl)
        }
      })
      return []
    })
  }, [])

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDragging(false)
      if (e.dataTransfer.files?.length) {
        addFiles(e.dataTransfer.files)
      }
    },
    [addFiles],
  )

  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const items = e.clipboardData?.items
      if (!items) return

      const files: File[] = []
      for (const item of Array.from(items)) {
        if (item.kind === 'file') {
          const file = item.getAsFile()
          if (file) files.push(file)
        }
      }
      if (files.length > 0) {
        addFiles(files)
      }
    },
    [addFiles],
  )

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) {
        addFiles(e.target.files)
        e.target.value = '' // Reset for re-selection
      }
    },
    [addFiles],
  )

  return {
    attachments,
    isDragging,
    addFiles,
    removeAttachment,
    clearAttachments,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handlePaste,
    handleFileChange,
  }
}
