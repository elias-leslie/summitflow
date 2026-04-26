import type { CollabAnnotation } from '@/lib/api/collab'

interface CollabAnnotationLayerProps {
  annotations: CollabAnnotation[]
}

export function CollabAnnotationLayer({
  annotations,
}: CollabAnnotationLayerProps): React.ReactElement {
  return (
    <div className="relative min-h-[260px] overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
      <div className="absolute inset-0 bg-[linear-gradient(rgba(148,163,184,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(148,163,184,0.08)_1px,transparent_1px)] bg-[size:32px_32px]" />
      <div className="absolute inset-x-0 top-0 border-b border-slate-800 bg-slate-950/90 px-3 py-2 text-xs text-slate-400">
        Shared review surface
      </div>
      {annotations.map((annotation, index) => {
        const x = Number(annotation.anchor.x ?? 80 + index * 36)
        const y = Number(annotation.anchor.y ?? 80 + index * 28)
        const width = Number(annotation.anchor.width ?? 160)
        const height = Number(annotation.anchor.height ?? 84)
        const viewportWidth = Number(annotation.anchor.viewport_width ?? 1440)
        const viewportHeight = Number(annotation.anchor.viewport_height ?? 900)
        const left = `${Math.max(0, Math.min(94, (x / viewportWidth) * 100))}%`
        const top = `${Math.max(10, Math.min(88, (y / viewportHeight) * 100))}%`
        const boxWidth = `${Math.max(6, Math.min(40, (width / viewportWidth) * 100))}%`
        const boxHeight = `${Math.max(6, Math.min(32, (height / viewportHeight) * 100))}%`

        if (annotation.kind === 'box' || annotation.kind === 'highlight') {
          return (
            <div
              key={annotation.annotation_id}
              className="absolute rounded border-2 border-cyan-300 bg-cyan-300/10 shadow-lg shadow-black/40"
              style={{ left, top, width: boxWidth, height: boxHeight }}
              title={annotation.comment}
            />
          )
        }

        return (
          <div
            key={annotation.annotation_id}
            className="absolute -ml-3 -mt-3 flex h-6 w-6 items-center justify-center rounded-full border border-amber-200 bg-amber-400 text-[10px] font-semibold text-slate-950 shadow-lg shadow-black/40"
            style={{ left, top }}
            title={annotation.comment}
          >
            {index + 1}
          </div>
        )
      })}
      {annotations.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-slate-500">
          No shared marks yet
        </div>
      )}
    </div>
  )
}
