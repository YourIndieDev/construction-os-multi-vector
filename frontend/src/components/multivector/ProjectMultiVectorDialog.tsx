'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Database, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  dialogBodyClassName,
} from '@/components/ui/dialog'
import {
  drawingExtractionApi,
  type MultiVectorSourceStatus,
} from '@/lib/api/drawing-extraction'
import { formatApiError } from '@/lib/utils/error-handler'
import { cn } from '@/lib/utils'

type SourceAction = 'enable' | 'disable' | 'rebuild'

interface ProjectMultiVectorDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  projectId: string
  projectName?: string
}

function readableStatus(status: string) {
  return status.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

async function runSourceAction(
  projectId: string,
  sourceId: string,
  action: SourceAction
): Promise<MultiVectorSourceStatus> {
  switch (action) {
    case 'enable':
      return drawingExtractionApi.enableMultiVectorSource(projectId, sourceId)
    case 'disable':
      return drawingExtractionApi.disableMultiVectorSource(projectId, sourceId)
    case 'rebuild':
      return drawingExtractionApi.rebuildMultiVectorSource(projectId, sourceId)
    default: {
      const _exhaustive: never = action
      return _exhaustive
    }
  }
}

export function ProjectMultiVectorDialog({
  open,
  onOpenChange,
  projectId,
  projectName,
}: ProjectMultiVectorDialogProps) {
  const [sources, setSources] = useState<MultiVectorSourceStatus[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [isLoading, setIsLoading] = useState(false)
  const [isActing, setIsActing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadSources = useCallback(async (silent = false) => {
    if (!projectId) return
    if (!silent) setIsLoading(true)
    setError(null)
    try {
      const body = await drawingExtractionApi.listMultiVectorProjectSources(projectId)
      setSources(body.sources ?? [])
    } catch (loadError) {
      setError(formatApiError(loadError) || 'Unable to load project sources.')
    } finally {
      if (!silent) setIsLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    if (open) {
      setSelectedIds(new Set())
      void loadSources()
    }
  }, [open, loadSources])

  const hasActiveJobs = useMemo(
    () => sources.some((source) => source.status === 'queued' || source.status === 'indexing'),
    [sources]
  )

  useEffect(() => {
    if (!open || !hasActiveJobs) return
    const timer = window.setInterval(() => {
      void loadSources(true)
    }, 2000)
    return () => window.clearInterval(timer)
  }, [open, hasActiveJobs, loadSources])

  const eligibleSourceIds = useMemo(
    () =>
      sources
        .filter((source) => Boolean(source.current_file_hash) && !source.file_error)
        .map((source) => source.source_id),
    [sources]
  )

  const selectedCount = selectedIds.size

  const toggleSource = (sourceId: string, checked: boolean) => {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (checked) next.add(sourceId)
      else next.delete(sourceId)
      return next
    })
  }

  const runSelectedAction = async (action: SourceAction) => {
    const sourceIds = Array.from(selectedIds)
    if (sourceIds.length === 0) return

    setIsActing(true)
    setError(null)
    try {
      const updated = await Promise.all(
        sourceIds.map(async (sourceId) => {
          try {
            return await runSourceAction(projectId, sourceId, action)
          } catch (actionError) {
            throw new Error(
              `${sourceId}: ${formatApiError(actionError) || 'Action failed.'}`
            )
          }
        })
      )

      const updatedById = new Map(updated.map((source) => [source.source_id, source]))
      setSources((current) =>
        current.map((source) => updatedById.get(source.source_id) ?? source)
      )
      setSelectedIds(new Set())

      const label =
        action === 'enable'
          ? 'queued for visual indexing'
          : action === 'disable'
            ? 'disabled'
            : 'queued for a clean rebuild'
      toast.success(`${updated.length} visual index source${updated.length === 1 ? '' : 's'} ${label}.`)
      if (action !== 'disable') {
        window.setTimeout(() => void loadSources(true), 500)
      }
    } catch (actionError) {
      const message = actionError instanceof Error ? actionError.message : 'Action failed.'
      setError(message)
      toast.error(message)
    } finally {
      setIsActing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[72vh] max-h-[72vh] w-[min(94vw,56rem)] max-w-[56rem]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Database className="h-4 w-4" />
            Visual multi-vector index
          </DialogTitle>
          <DialogDescription>
            Select PDF sources in {projectName || 'this project'}. Starting an index renders
            their pages, embeds the images with ColSmol, and stores the visual vectors in Qdrant.
          </DialogDescription>
        </DialogHeader>

        <div className={cn(dialogBodyClassName, 'space-y-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/30 px-3 py-2">
            <div className="text-sm">
              <span className="font-medium">{selectedCount}</span> selected
              <span className="ml-2 text-muted-foreground">
                {eligibleSourceIds.length} eligible PDF source{eligibleSourceIds.length === 1 ? '' : 's'}
              </span>
              {hasActiveJobs ? (
                <span className="ml-2 font-medium text-blue-600">Indexing in progress</span>
              ) : null}
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={isLoading || isActing || eligibleSourceIds.length === 0}
                onClick={() => setSelectedIds(new Set(eligibleSourceIds))}
              >
                Select eligible
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={isActing || selectedCount === 0}
                onClick={() => setSelectedIds(new Set())}
              >
                Clear
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={isLoading || isActing}
                onClick={() => void loadSources()}
                aria-label="Refresh visual index status"
              >
                <RefreshCw className={cn('h-4 w-4', (isLoading || hasActiveJobs) && 'animate-spin')} />
              </Button>
            </div>
          </div>

          {error ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          {isLoading ? (
            <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
              Loading project sources…
            </div>
          ) : sources.length === 0 ? (
            <div className="flex min-h-40 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
              No project sources were found.
            </div>
          ) : (
            <div className="divide-y rounded-md border">
              {sources.map((source) => {
                const eligible = Boolean(source.current_file_hash) && !source.file_error
                const selected = selectedIds.has(source.source_id)
                const active = source.status === 'queued' || source.status === 'indexing'
                return (
                  <label
                    className={cn(
                      'flex items-start gap-3 px-3 py-2.5',
                      eligible ? 'cursor-pointer hover:bg-muted/40' : 'cursor-not-allowed opacity-60'
                    )}
                    key={source.source_id}
                  >
                    <Checkbox
                      checked={selected}
                      disabled={!eligible || isActing || active}
                      onCheckedChange={(checked) =>
                        toggleSource(source.source_id, checked === true)
                      }
                      aria-label={`Select ${source.source_title || source.source_id}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">
                          {source.source_title || 'Untitled source'}
                        </span>
                        <div className="flex items-center gap-2 text-xs">
                          <span
                            className={cn(
                              'rounded-full border px-2 py-0.5',
                              active && 'border-blue-500/50 text-blue-600',
                              source.status === 'ready' && 'border-emerald-500/50 text-emerald-600',
                              source.status === 'error' && 'border-destructive/50 text-destructive'
                            )}
                          >
                            {readableStatus(source.status)}
                          </span>
                          <span className="text-muted-foreground">
                            {source.point_count} point{source.point_count === 1 ? '' : 's'}
                          </span>
                        </div>
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {source.source_id}
                      </div>
                      {active ? (
                        <div className="mt-1 text-xs text-blue-600">
                          ColSmol is processing page and crop images. This view refreshes automatically.
                        </div>
                      ) : null}
                      {source.stale ? (
                        <div className="mt-1 text-xs font-medium text-amber-600">
                          File changed since the last visual index.
                        </div>
                      ) : null}
                      {source.file_error || source.last_error || source.qdrant_error ? (
                        <div className="mt-1 text-xs text-destructive">
                          {source.file_error || source.last_error || source.qdrant_error}
                        </div>
                      ) : null}
                    </div>
                  </label>
                )
              })}
            </div>
          )}
        </div>

        <DialogFooter className="border-t pt-2">
          <Button
            type="button"
            variant="outline"
            disabled={isActing || selectedCount === 0}
            onClick={() => void runSelectedAction('disable')}
          >
            Disable selected
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={isActing || selectedCount === 0}
            onClick={() => void runSelectedAction('rebuild')}
          >
            Rebuild selected
          </Button>
          <Button
            type="button"
            disabled={isActing || selectedCount === 0}
            onClick={() => void runSelectedAction('enable')}
          >
            Enable and index selected
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
