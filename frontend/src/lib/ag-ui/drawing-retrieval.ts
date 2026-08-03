import type { AgUiEvent } from '@/lib/ag-ui/events'
import type { DrawingRetrievalDebug } from '@/lib/types/drawing-retrieval'

export const DRAWING_RETRIEVAL_DEBUG_EVENT = 'drawing_retrieval_debug'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function parseDrawingRetrievalDebugEvent(
  event: AgUiEvent
): DrawingRetrievalDebug | null {
  if (event.type !== 'CUSTOM' || event.name !== DRAWING_RETRIEVAL_DEBUG_EVENT) {
    return null
  }
  if (!isRecord(event.value)) return null

  const value = event.value
  const requestedMode = value.requested_mode
  const projectId = value.project_id
  if (
    requestedMode !== 'existing' &&
    requestedMode !== 'multi_vector' &&
    requestedMode !== 'compare'
  ) {
    return null
  }
  if (typeof projectId !== 'string' || !projectId) return null

  return value as unknown as DrawingRetrievalDebug
}
