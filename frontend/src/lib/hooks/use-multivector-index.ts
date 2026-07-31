'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const API_ROOT = '/api/drawing-extractions/multivector'

export type MultiVectorSourceStatus = {
  project_id: string
  source_id: string
  source_title?: string | null
  enabled: boolean
  status: 'disabled' | 'not_indexed' | 'queued' | 'indexing' | 'ready' | 'stale' | 'error'
  persisted_status: string
  stale: boolean
  point_count: number
  current_file_hash?: string | null
  indexed_file_hash?: string | null
  indexed_run_id?: string | null
  last_error?: string | null
  file_error?: string | null
  qdrant_error?: string | null
}

type SourceAction = 'enable' | 'disable' | 'rebuild'

function sourceEndpoint(projectId: string, sourceId: string, action?: SourceAction) {
  const base = `${API_ROOT}/projects/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}`
  return action ? `${base}/${action}` : base
}

async function responseError(response: Response) {
  try {
    const body = await response.json()
    return typeof body.detail === 'string'
      ? body.detail
      : JSON.stringify(body.detail ?? body)
  } catch {
    return `${response.status} ${response.statusText}`
  }
}

async function requestStatus(projectId: string, sourceId: string) {
  const response = await fetch(sourceEndpoint(projectId, sourceId), {
    cache: 'no-store',
  })
  if (!response.ok) throw new Error(await responseError(response))
  return (await response.json()) as MultiVectorSourceStatus
}

async function runAction(projectId: string, sourceId: string, action: SourceAction) {
  const response = await fetch(sourceEndpoint(projectId, sourceId, action), {
    method: 'POST',
  })
  if (!response.ok) throw new Error(await responseError(response))
  return (await response.json()) as MultiVectorSourceStatus
}

export function useMultiVectorSourceIndex(
  projectId: string | undefined,
  sourceId: string | undefined,
  enabled = true
) {
  const queryClient = useQueryClient()
  const queryKey = ['multi-vector-source-index', projectId, sourceId] as const
  const canRun = Boolean(projectId && sourceId)

  const statusQuery = useQuery({
    queryKey,
    queryFn: () => requestStatus(projectId!, sourceId!),
    enabled: enabled && canRun,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'queued' || status === 'indexing' ? 2000 : false
    },
  })

  const mutation = useMutation({
    mutationFn: (action: SourceAction) => runAction(projectId!, sourceId!, action),
    onSuccess: (status) => {
      queryClient.setQueryData(queryKey, status)
      void queryClient.invalidateQueries({ queryKey })
    },
  })

  return {
    status: statusQuery.data,
    statusQuery,
    startIndex: () => mutation.mutateAsync('enable'),
    rebuild: () => mutation.mutateAsync('rebuild'),
    disable: () => mutation.mutateAsync('disable'),
    isBusy:
      mutation.isPending ||
      statusQuery.data?.status === 'queued' ||
      statusQuery.data?.status === 'indexing',
    error: mutation.error ?? statusQuery.error,
  }
}
