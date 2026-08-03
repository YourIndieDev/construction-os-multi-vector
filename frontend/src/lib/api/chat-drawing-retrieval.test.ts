import { beforeEach, describe, expect, it } from 'vitest'
import { buildProjectChatTransport } from '@/lib/api/chat'
import { useDrawingRetrievalStore } from '@/lib/stores/drawing-retrieval-store'

const request = {
  session_id: 'chat_session:test',
  message: 'Where is the regulator?',
  context_config: {
    sources: { 'source:p203': 'full content' },
    notes: {},
  },
}

describe('project chat drawing retrieval transport', () => {
  beforeEach(() => {
    useDrawingRetrievalStore.setState({
      request: {
        projectId: null,
        mode: 'existing',
        selectedSourceIds: [],
        resultLimit: 3,
      },
      pendingDebug: null,
      debugByMessageId: {},
    })
  })

  it('keeps the normal endpoint and unchanged body in existing mode', () => {
    useDrawingRetrievalStore.getState().setActiveProject('project:test')

    const transport = buildProjectChatTransport(request)

    expect(transport.url).toBe('/api/chat/execute')
    expect(transport.body).toEqual(request)
    expect(transport.body).not.toHaveProperty('drawing_retrieval_mode')
  })

  it('uses the isolated endpoint with selected ready sources in compare mode', () => {
    const store = useDrawingRetrievalStore.getState()
    store.setActiveProject('project:test')
    store.setSelectedSourceIds(['source:p203'])
    store.setMode('compare')

    const transport = buildProjectChatTransport(request)

    expect(transport.url).toBe(
      '/api/drawing-extractions/multivector/chat/execute'
    )
    expect(transport.body).toMatchObject({
      drawing_retrieval_mode: 'compare',
      drawing_source_ids: ['source:p203'],
      drawing_result_limit: 3,
    })
  })

  it('fails closed to existing when visual mode has no selected source', () => {
    const store = useDrawingRetrievalStore.getState()
    store.setActiveProject('project:test')
    store.setMode('multi_vector')

    expect(buildProjectChatTransport(request).url).toBe('/api/chat/execute')
  })
})
