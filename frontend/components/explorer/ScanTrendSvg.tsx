/**
 * ScanTrendSvg - SVG trend line visualization
 */

'use client'

interface ScanTrendSvgProps {
  linePath: string
  areaPath: string
}

export function ScanTrendSvg({ linePath, areaPath }: ScanTrendSvgProps) {
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full"
      style={{ top: '8px', height: 'calc(100% - 8px)' }}
    >
      <defs>
        <linearGradient id="scanAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#a855f7" stopOpacity="0.12" />
          <stop offset="100%" stopColor="#a855f7" stopOpacity="0" />
        </linearGradient>
      </defs>
      {areaPath && <path d={areaPath} fill="url(#scanAreaGrad)" />}
      <path
        d={linePath}
        fill="none"
        stroke="#a855f7"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}
