'use client';

import { useState } from 'react';
import { CheckCircle, Loader2 } from 'lucide-react';
import { clsx } from 'clsx';

interface Pattern {
  id: string;
  confidence: number;
  status: string;
}

interface BulkActionsBarProps {
  patterns: Pattern[];
  onBulkApprove: (patternIds: string[]) => Promise<void>;
  confidenceThreshold?: number;
  className?: string;
}

export function BulkActionsBar({
  patterns,
  onBulkApprove,
  confidenceThreshold = 0.85,
  className,
}: BulkActionsBarProps) {
  const [loading, setLoading] = useState(false);

  // Get pending patterns that meet the confidence threshold
  const highConfidencePatterns = patterns.filter(
    (p) => p.status === 'pending' && p.confidence >= confidenceThreshold
  );

  const handleBulkApprove = async () => {
    if (highConfidencePatterns.length === 0 || loading) return;

    setLoading(true);
    try {
      await onBulkApprove(highConfidencePatterns.map((p) => p.id));
    } finally {
      setLoading(false);
    }
  };

  if (highConfidencePatterns.length === 0) {
    return null;
  }

  return (
    <div className={clsx('flex items-center justify-end', className)}>
      <button
        onClick={handleBulkApprove}
        disabled={loading}
        className={clsx(
          'flex items-center gap-2 px-4 py-2 text-[13px] font-medium',
          'bg-emerald-500/15 border border-emerald-500/30 rounded-lg',
          'text-emerald-400 transition-all duration-150',
          loading
            ? 'opacity-50 cursor-not-allowed'
            : 'hover:bg-emerald-500/25 cursor-pointer'
        )}
      >
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <CheckCircle className="w-4 h-4" />
        )}
        Approve All High-Confidence ({highConfidencePatterns.length})
      </button>
    </div>
  );
}
