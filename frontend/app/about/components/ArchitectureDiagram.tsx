import { FileCode2, Layers, Zap } from 'lucide-react'

export function ArchitectureDiagram(): React.ReactElement {
  return (
    <div
      className="p-8 rounded-xl border border-slate-800 bg-slate-900/50"
      style={{
        backgroundImage: `
          radial-gradient(circle at 20% 30%, rgba(255, 102, 0, 0.05) 0%, transparent 50%),
          radial-gradient(circle at 80% 70%, rgba(255, 0, 102, 0.05) 0%, transparent 50%)
        `,
      }}
    >
      <div className="grid grid-cols-3 gap-8 max-w-3xl mx-auto">
        {/* Frontend */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background:
                'linear-gradient(135deg, rgba(0, 245, 255, 0.15) 0%, rgba(0, 245, 255, 0.05) 100%)',
              border: '1px solid rgba(0, 245, 255, 0.3)',
            }}
          >
            <Layers className="w-10 h-10 text-phosphor-500" />
          </div>
          <h4 className="font-medium text-white mb-1">Frontend</h4>
          <p className="text-xs text-slate-500">Next.js + React</p>
        </div>

        {/* Backend */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background:
                'linear-gradient(135deg, rgba(255, 102, 0, 0.15) 0%, rgba(255, 102, 0, 0.05) 100%)',
              border: '1px solid rgba(255, 102, 0, 0.3)',
            }}
          >
            <Zap className="w-10 h-10 text-sunset-orange" />
          </div>
          <h4 className="font-medium text-white mb-1">Backend</h4>
          <p className="text-xs text-slate-500">FastAPI + Python</p>
        </div>

        {/* Database */}
        <div className="text-center">
          <div
            className="w-20 h-20 mx-auto rounded-2xl flex items-center justify-center mb-4"
            style={{
              background:
                'linear-gradient(135deg, rgba(255, 0, 102, 0.15) 0%, rgba(255, 0, 102, 0.05) 100%)',
              border: '1px solid rgba(255, 0, 102, 0.3)',
            }}
          >
            <FileCode2 className="w-10 h-10 text-outrun-500" />
          </div>
          <h4 className="font-medium text-white mb-1">Database</h4>
          <p className="text-xs text-slate-500">PostgreSQL</p>
        </div>
      </div>

      {/* Connection lines */}
      <div className="flex justify-center mt-6">
        <div className="flex items-center gap-4 text-xs text-slate-600">
          <div className="flex items-center gap-2">
            <div className="w-8 h-px bg-gradient-to-r from-phosphor-500 to-sunset-orange" />
            <span>REST API</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-px bg-gradient-to-r from-sunset-orange to-outrun-500" />
            <span>SQL</span>
          </div>
        </div>
      </div>
    </div>
  )
}
