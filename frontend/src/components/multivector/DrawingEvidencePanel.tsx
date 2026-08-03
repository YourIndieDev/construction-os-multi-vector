'use client'

import { useEffect, useMemo, useState } from 'react'
import { ExternalLink, ImageIcon, Timer } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { drawingExtractionApi } from '@/lib/api/drawing-extraction'
import type {
  DrawingRetrievalDebug,
  DrawingRetrievalRankingDebug,
  DrawingVisualEvidenceDebug,
} from '@/lib/types/drawing-retrieval'

function useEvidenceImage(path?: string | null) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    let active = true
    let objectUrl: string | null = null
    setUrl(null)
    setError(false)
    if (!path) return

    void drawingExtractionApi
      .fetchMultiVectorEvidenceImage(path)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(() => {
        if (active) setError(true)
      })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  return { url, error }
}

function modeLabel(mode: string): string {
  if (mode === 'multi_vector') return 'Multi-vector'
  if (mode === 'compare') return 'Compare'
  return 'Existing'
}

function durationLabel(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)} ms` : 'n/a'
}

function RankingSummary({
  title,
  ranking,
}: {
  title: string
  ranking?: DrawingRetrievalRankingDebug | null
}) {
  if (!ranking) return null
  return (
    <div className="rounded-md border bg-background/70 p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium">{title}</span>
        <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
          <Timer className="h-3 w-3" />
          {durationLabel(ranking.duration_ms)}
        </span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">
        {ranking.result_count} result{ranking.result_count === 1 ? '' : 's'}
        {ranking.score_space ? ` · ${ranking.score_space}` : ''}
      </p>
      {ranking.error ? (
        <p className="mt-1 line-clamp-2 text-[10px] text-destructive">{ranking.error}</p>
      ) : null}
      {ranking.results?.length ? (
        <ul className="mt-1 space-y-0.5 text-[10px] text-muted-foreground">
          {ranking.results.slice(0, 3).map((result, index) => (
            <li key={result.id || `${title}-${index}`} className="truncate">
              {result.sheet_number || result.title || result.source_title || result.source_id || `Result ${index + 1}`}
              {typeof result.score === 'number' ? ` · ${result.score.toFixed(3)}` : ''}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function EvidenceCard({ evidence }: { evidence: DrawingVisualEvidenceDebug }) {
  const crop = useEvidenceImage(evidence.crop_path)
  const parent = useEvidenceImage(evidence.parent_page_path)
  const label = evidence.sheet_number || evidence.source_title

  const openParent = () => {
    if (!parent.url) return
    window.open(parent.url, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="overflow-hidden rounded-md border bg-background">
      <div className="aspect-[4/3] bg-muted/40">
        {crop.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={crop.url}
            alt={`Retrieved crop from ${label}`}
            className="h-full w-full object-contain"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <ImageIcon className="h-5 w-5" />
            <span className="ml-1.5 text-[10px]">{crop.error ? 'Preview unavailable' : 'Loading preview…'}</span>
          </div>
        )}
      </div>
      <div className="space-y-1 p-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-[11px] font-medium">{evidence.source_title}</p>
            <p className="text-[10px] text-muted-foreground">
              Sheet {evidence.sheet_number || 'unknown'} · Page {evidence.page_number}
            </p>
          </div>
          <Badge variant="secondary" className="h-5 shrink-0 px-1.5 text-[9px]">
            {evidence.score.toFixed(3)}
          </Badge>
        </div>
        {parent.url ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-6 w-full justify-start px-1.5 text-[10px]"
            onClick={openParent}
          >
            <ExternalLink className="mr-1 h-3 w-3" />
            Open full drawing page
          </Button>
        ) : null}
      </div>
    </div>
  )
}

export function DrawingEvidencePanel({ debug }: { debug: DrawingRetrievalDebug }) {
  const evidence = debug.evidence || []
  const retrievalLabel = modeLabel(debug.mode_used || debug.requested_mode)
  const summary = useMemo(() => {
    if (debug.fallback_reason) return `${retrievalLabel} · fallback used`
    return `${retrievalLabel} · ${evidence.length} visual result${evidence.length === 1 ? '' : 's'}`
  }, [debug.fallback_reason, evidence.length, retrievalLabel])

  if (
    debug.requested_mode === 'existing' &&
    !debug.existing &&
    !debug.multi_vector &&
    !debug.fallback_reason &&
    evidence.length === 0
  ) {
    return (
      <div className="mt-1.5" data-testid="drawing-retrieval-method">
        <Badge variant="outline" className="h-5 px-1.5 text-[9px] font-normal">
          Existing retrieval
        </Badge>
      </div>
    )
  }

  return (
    <div className="mt-2 w-full" data-testid="drawing-evidence-panel">
      <details className="rounded-lg border border-dashed bg-muted/20">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-2 text-xs">
          <span className="flex min-w-0 items-center gap-1.5">
            <ImageIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <span className="truncate font-medium">Retrieved evidence</span>
            <Badge variant="outline" className="h-5 px-1.5 text-[9px] uppercase tracking-wide">
              Experimental
            </Badge>
          </span>
          <span className="shrink-0 text-[10px] text-muted-foreground">{summary}</span>
        </summary>

        <div className="space-y-2 border-t px-2.5 py-2">
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            <RankingSummary title="Existing retrieval" ranking={debug.existing} />
            <RankingSummary title="Multi-vector retrieval" ranking={debug.multi_vector} />
          </div>

          {debug.fallback_reason ? (
            <p className="rounded border border-amber-500/30 bg-amber-500/5 p-2 text-[10px] text-amber-700 dark:text-amber-300">
              Fallback: {debug.fallback_reason}
            </p>
          ) : null}

          {evidence.length ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {evidence.slice(0, 3).map((item) => (
                <EvidenceCard
                  key={item.qdrant_point_id || `${item.source_id}-${item.page_number}-${item.rank}`}
                  evidence={item}
                />
              ))}
            </div>
          ) : (
            <p className="py-2 text-center text-[10px] text-muted-foreground">
              No inspectable drawing images were attached to this response.
            </p>
          )}

          {debug.vision ? (
            <p className="text-[10px] text-muted-foreground">
              Vision: {debug.vision.supported ? 'enabled' : 'not attached'}
              {debug.vision.model_name ? ` · ${debug.vision.model_name}` : ''}
              {typeof debug.vision.image_count === 'number' ? ` · ${debug.vision.image_count} images` : ''}
            </p>
          ) : null}
        </div>
      </details>
    </div>
  )
}
