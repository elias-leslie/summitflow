import { FileCode } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

interface FilesModifiedProps {
  files: string[]
}

export function FilesModified({ files }: FilesModifiedProps) {
  if (files.length === 0) return null

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500">
        <FileCode className="h-3.5 w-3.5" />
        Files Modified
      </div>
      <div className="flex flex-wrap gap-1">
        {files.slice(0, 5).map((file, i) => (
          <Badge key={i} variant="outline" className="text-xs font-mono">
            {file.split('/').pop()}
          </Badge>
        ))}
        {files.length > 5 && (
          <Badge variant="secondary" className="text-xs">
            +{files.length - 5}
          </Badge>
        )}
      </div>
    </div>
  )
}
