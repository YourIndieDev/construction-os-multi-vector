import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAgUiChatSseHandler } from '@/lib/hooks/chat-sse-handlers'
import { useDrawingRetrievalStore } from '@/lib/stores/drawing-retrieval-store'

function mutableRef<T>(current: T) {
  return { current }
}

function buildHandler() {
  return createAgUiChatSseHandler(
    {
      aiMessageIdRef: mutableRef<string | null>(null),
      streamContentRef: mutableRef(new Map<string, string>()),
      streamRafRef: mutableRef<number | null>(null),
      setMessages: vi.fn(),
      setStreamStatus: vi.fn(),
      setActivityLog: vi.fn(),
      setLiveMcpToolCalls: vi.fn(),
      appendStreamingDelta: vi.fn(),
      flushStreamingContent: vi.fn(),
      clearStreamingBuffers: vi.fn(),
      t: ((key: string) => key) as never,
      createAiMessage: (id, content) => ({ id, type: 'ai' as const, content }),
    },
    { flushOnTextMessageEnd: true }
  )
}

describe('drawing retrieval AG-UI event binding', () => {
  beforeEach(() => {
    useDrawingRetrievalStore.setState({
      request: {
        projectId: 'project:test',
        mode: 'compare',
        selectedSourceIds: ['source:p203'],
        resultLimit: 3,
      },
      debugByMessageId: {},
      pendingDebug: null,
    })
  })

  it('holds early debug and binds it when the assistant message starts', () => {
    const handler = buildHandler()

    handler({
      type: 'CUSTOM',
      name: 'drawing_retrieval_debug',
      value: {
        requested_mode: 'compare',
        mode_used: 'compare',
        project_id: 'project:test',
        requested_source_ids: ['source:p203'],
        existing: { result_count: 0 },
        multi_vector: { result_count: 1 },
        evidence: [],
      },
    })

    expect(useDrawingRetrievalStore.getState().pendingDebug?.mode_used).toBe('compare')

    handler({ type: 'TEXT_MESSAGE_START', messageId: 'ai:one' })

    expect(
      useDrawingRetrievalStore.getState().debugByMessageId['ai:one']?.requested_mode
    ).toBe('compare')
    expect(useDrawingRetrievalStore.getState().pendingDebug).toBeNull()
  })

  it('creates a compact existing-mode marker for an ordinary project turn', () => {
    useDrawingRetrievalStore.setState({
      request: {
        projectId: 'project:test',
        mode: 'existing',
        selectedSourceIds: [],
        resultLimit: 3,
      },
      debugByMessageId: {},
      pendingDebug: null,
    })

    buildHandler()({ type: 'TEXT_MESSAGE_START', messageId: 'ai:existing' })

    const debug =
      useDrawingRetrievalStore.getState().debugByMessageId['ai:existing']
    expect(debug.requested_mode).toBe('existing')
    expect(debug.evidence).toEqual([])
  })
})
