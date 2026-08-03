'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Database, RefreshCw, TriangleAlert } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  drawingExtractionApi,
  type MultiVectorSourceStatus,
} from '@/lib/api/drawing-extraction'
import { useDrawingRetrievalStore } from '@/lib/stores/drawing-retrieval-store'
import type { DrawingRetrievalMode } from '@/lib/types/drawing-retrieval'
import { cn } from '@/lib/utils'

interface ChatDrawingRetrievalControlsProps {
  projectId: string
  includedSourceIds: string[]
  disabled?: boolean
}

const MODES: Array<{ value: DrawingRetrievalMode; label: string }> = [
  { value: 'existing', label: 'Existing' },
  { value: 'multi_vector', label: 'Multi-vector' },
  { value: 'compare', label: 'Compare' },
]

function isReady(source: MultiVectorSourceStatus): boolean {
  return (
    source.enabled &&
    source.status === 'ready' &&
    !source.stale &&
    source.point_count > 0
  )
}

function isBusy(source: MultiVectorSourceStatus): boolean {
  return source.status === 'queued' || source.status === 'indexing'
}

function canIndex(source: MultiVectorSourceStatus): boolean {
  return !source.file_error && Boolean(source.current_file_hash)
}

function statusLabel(source: MultiVectorSourceStatus): string {
  if (source.stale) return 'Stale'
  if (source.status === 'ready') return `Ready · ${source.point_count} points`
  if (source.status === 'indexing') return 'Indexing'
  if (source.status === 'queued') return 'Queued'
  if (source.status === 'error') return 'Error'
  if (source.status === 'disabled') return 'Not indexed'
  return source.status.replaceAll('_', ' ')
}

export function ChatDrawingRetrievalControls({
  projectId,
  includedSourceIds,
  disabled = false,
}: ChatDrawingRetrievalControlsProps) {
  const request = useDrawingRetrievalStore((state) => state.request)
  const setActiveProject = useDrawingRetrievalStore(
    (state) => state.setActiveProject
  )
  const setMode = useDrawingRetrievalStore((state) => state.setMode)
  const setSelectedSourceIds = useDrawingRetrievalStore(
    (state) => state.setSelectedSourceIds
  )
  const clearProject = useDrawingRetrievalStore((state) => state.clearProject)

  const [sources, setSources] = useState<MultiVectorSourceStatus[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actingSourceId, setActingSourceId] = useState<string | null>(null)
  const initializedSelectionRef = useRef(false)

  const includedSet = useMemo(
    () => new Set(includedSourceIds),
    [includedSourceIds]
  )

  const loadSources = useCallback(async () => {
    try {
      const response =
        await drawingExtractionApi.listMultiVectorProjectSources(projectId)
      setSources(response.sources)
      setLoadError(null)
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : 'Unable to load visual index status'
      )
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    setActiveProject(projectId)
    initializedSelectionRef.current = false
    setLoading(true)
    void loadSources()
    return () => clearProject(projectId)
  }, [clearProject, loadSources, projectId, setActiveProject])

  useEffect(() => {
    if (!sources.some(isBusy)) return
    const timer = window.setInterval(() => void loadSources(), 2000)
    return () => window.clearInterval(timer)
  }, [loadSources, sources])

  const selectableReadyIds = useMemo(
    () =>
      sources
        .filter(
          (source) => isReady(source) && includedSet.has(source.source_id)
        )
        .map((source) => source.source_id),
    [includedSet, sources]
  )
  const selectableReadySet = useMemo(
    () => new Set(selectableReadyIds),
    [selectableReadyIds]
  )

  useEffect(() => {
    if (loading) return
    const stillValid = request.selectedSourceIds.filter((id) =>
      selectableReadySet.has(id)
    )
    if (!initializedSelectionRef.current) {
      initializedSelectionRef.current = true
      setSelectedSourceIds(selectableReadyIds)
      return
    }
    if (stillValid.length !== request.selectedSourceIds.length) {
      setSelectedSourceIds(stillValid)
    }
  }, [
    loading,
    request.selectedSourceIds,
    selectableReadyIds,
    selectableReadySet,
    setSelectedSourceIds,
  ])

  const selectedReadyCount = request.selectedSourceIds.filter((id) =>
    selectableReadySet.has(id)
  ).length
  const visualAvailable = selectedReadyCount > 0

  useEffect(() => {
    if (request.mode !== 'existing' && !visualAvailable) {
      setMode('existing')
    }
  }, [request.mode, setMode, visualAvailable])

  const toggleSource = (sourceId: string) => {
    if (!selectableReadySet.has(sourceId)) return
    const selected = request.selectedSourceIds.includes(sourceId)
    setSelectedSourceIds(
      selected
        ? request.selectedSourceIds.filter((id) => id !== sourceId)
        : [...request.selectedSourceIds, sourceId]
    )
  }

  const indexSource = async (source: MultiVectorSourceStatus) => {
    setActingSourceId(source.source_id)
    try {
      if (
        source.enabled &&
        (source.status === 'ready' || source.stale || source.status === 'error')
      ) {
        await drawingExtractionApi.rebuildMultiVectorSource(
          projectId,
          source.source_id
        )
      } else {
        await drawingExtractionApi.enableMultiVectorSource(
          projectId,
          source.source_id
        )
      }
      await loadSources()
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : 'Unable to update the visual index'
      )
    } finally {
      setActingSourceId(null)
    }
  }

  return (
    <div
      className="shrink-0 rounded-lg border border-dashed bg-muted/20 px-2.5 py-2"
      data-testid="drawing-retrieval-controls"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Database className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-medium">Drawing retrieval</span>
          <Badge
            variant="outline"
            className="h-5 px-1.5 text-[10px] uppercase tracking-wide"
          >
            Experimental
          </Badge>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[11px]"
          onClick={() => void loadSources()}
          disabled={loading || disabled}
        >
          <RefreshCw
            className={cn('mr-1 h-3 w-3', loading && 'animate-spin')}
          />
          Refresh
        </Button>
      </div>

      <div
        className="mt-2 grid grid-cols-3 gap-1"
        role="group"
        aria-label="Drawing retrieval method"
      >
        {MODES.map((mode) => {
          const unavailable = mode.value !== 'existing' && !visualAvailable
          return (
            <Button
              key={mode.value}
              type="button"
              size="sm"
              variant={request.mode === mode.value ? 'default' : 'outline'}
              className="h-7 px-2 text-[11px]"
              disabled={disabled || unavailable}
              onClick={() => setMode(mode.value)}
              title={
                unavailable ? 'Select a ready indexed source first' : undefined
              }
            >
              {mode.label}
            </Button>
          )
        })}
      </div>

      <details className="mt-2 text-xs">
        <summary className="cursor-pointer select-none text-muted-foreground">
          Sources · {selectedReadyCount} selected · {selectableReadyIds.length}{' '}
          ready
        </summary>
        <div className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-1">
          {loadError ? (
            <div className="flex items-start gap-1.5 rounded border border-destructive/40 bg-destructive/5 p-2 text-destructive">
              <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{loadError}</span>
            </div>
          ) : null}
          {!loading && sources.length === 0 ? (
            <p className="py-2 text-muted-foreground">
              No project sources are eligible for visual indexing.
            </p>
          ) : null}
          {sources.map((source) => {
            const ready = isReady(source)
            const included = includedSet.has(source.source_id)
            const selectable = ready && included
            const selected = request.selectedSourceIds.includes(source.source_id)
            const actionBusy = actingSourceId === source.source_id || isBusy(source)
            const error =
              source.last_error || source.file_error || source.qdrant_error
            return (
              <div
                key={source.source_id}
                className="rounded-md border bg-background p-2"
              >
                <div className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-3.5 w-3.5"
                    aria-label={`Use ${source.source_title || source.source_id}`}
                    checked={selected}
                    disabled={disabled || !selectable}
                    onChange={() => toggleSource(source.source_id)}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">
                      {source.source_title || source.source_id}
                    </p>
                    <p
                      className={cn(
                        'text-[11px] text-muted-foreground',
                        source.status === 'error' && 'text-destructive'
                      )}
                    >
                      {statusLabel(source)}
                      {!included ? ' · Excluded from chat context' : ''}
                    </p>
                    {error ? (
                      <p className="mt-1 line-clamp-2 text-[11px] text-destructive">
                        {error}
                      </p>
                    ) : null}
                  </div>
                  {canIndex(source) && !ready ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-6 shrink-0 px-2 text-[10px]"
                      disabled={disabled || actionBusy}
                      onClick={() => void indexSource(source)}
                    >
                      {actionBusy
                        ? 'Working…'
                        : source.enabled
                          ? 'Rebuild'
                          : 'Index'}
                    </Button>
                  ) : null}
                  {ready ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="h-6 shrink-0 px-2 text-[10px]"
                      disabled={disabled || actionBusy}
                      onClick={() => void indexSource(source)}
                    >
                      Rebuild
                    </Button>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      </details>
    </div>
  )
}
