'use client'

import { create } from 'zustand'
import type {
  DrawingRetrievalDebug,
  DrawingRetrievalMode,
  DrawingRetrievalRequestOptions,
} from '@/lib/types/drawing-retrieval'

const DEFAULT_OPTIONS: DrawingRetrievalRequestOptions = {
  projectId: null,
  mode: 'existing',
  selectedSourceIds: [],
  resultLimit: 3,
}

interface DrawingRetrievalState {
  request: DrawingRetrievalRequestOptions
  debugByMessageId: Record<string, DrawingRetrievalDebug>
  pendingDebug: DrawingRetrievalDebug | null
  setActiveProject: (projectId: string | null) => void
  setMode: (mode: DrawingRetrievalMode) => void
  setSelectedSourceIds: (sourceIds: string[]) => void
  setResultLimit: (limit: number) => void
  captureDebug: (debug: DrawingRetrievalDebug, messageId?: string | null) => void
  bindPendingDebug: (messageId: string) => void
  clearPendingDebug: () => void
  hydrateMessageDebug: (messageId: string, debug: DrawingRetrievalDebug) => void
  clearProject: (projectId: string) => void
}

function uniqueSourceIds(sourceIds: string[]): string[] {
  return Array.from(new Set(sourceIds.filter(Boolean))).sort()
}

export const useDrawingRetrievalStore = create<DrawingRetrievalState>((set, get) => ({
  request: DEFAULT_OPTIONS,
  debugByMessageId: {},
  pendingDebug: null,

  setActiveProject: (projectId) =>
    set((state) => {
      if (state.request.projectId === projectId) return state
      return {
        request: {
          ...DEFAULT_OPTIONS,
          projectId,
        },
        pendingDebug: null,
      }
    }),

  setMode: (mode) =>
    set((state) => ({ request: { ...state.request, mode } })),

  setSelectedSourceIds: (selectedSourceIds) =>
    set((state) => ({
      request: {
        ...state.request,
        selectedSourceIds: uniqueSourceIds(selectedSourceIds),
      },
    })),

  setResultLimit: (resultLimit) =>
    set((state) => ({
      request: {
        ...state.request,
        resultLimit: Math.max(1, Math.min(3, resultLimit)),
      },
    })),

  captureDebug: (debug, messageId) => {
    const resolvedMessageId = messageId || debug.message_id || null
    if (resolvedMessageId) {
      set((state) => ({
        debugByMessageId: {
          ...state.debugByMessageId,
          [resolvedMessageId]: debug,
        },
        pendingDebug: null,
      }))
      return
    }
    set({ pendingDebug: debug })
  },

  bindPendingDebug: (messageId) => {
    const pending = get().pendingDebug
    if (!pending) return
    set((state) => ({
      debugByMessageId: {
        ...state.debugByMessageId,
        [messageId]: pending,
      },
      pendingDebug: null,
    }))
  },

  clearPendingDebug: () => set({ pendingDebug: null }),

  hydrateMessageDebug: (messageId, debug) =>
    set((state) => ({
      debugByMessageId: {
        ...state.debugByMessageId,
        [messageId]: debug,
      },
    })),

  clearProject: (projectId) =>
    set((state) =>
      state.request.projectId === projectId
        ? { request: DEFAULT_OPTIONS, pendingDebug: null }
        : state
    ),
}))

export function getActiveDrawingRetrievalRequest(): DrawingRetrievalRequestOptions {
  return useDrawingRetrievalStore.getState().request
}
