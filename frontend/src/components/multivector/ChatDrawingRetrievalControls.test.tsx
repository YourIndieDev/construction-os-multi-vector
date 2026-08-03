import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ChatDrawingRetrievalControls } from './ChatDrawingRetrievalControls'
import { useDrawingRetrievalStore } from '@/lib/stores/drawing-retrieval-store'

const listSources = vi.fn()
const enableSource = vi.fn()
const rebuildSource = vi.fn()

vi.mock('@/lib/api/drawing-extraction', () => ({
  drawingExtractionApi: {
    listMultiVectorProjectSources: (...args: unknown[]) => listSources(...args),
    enableMultiVectorSource: (...args: unknown[]) => enableSource(...args),
    rebuildMultiVectorSource: (...args: unknown[]) => rebuildSource(...args),
  },
}))

const readySource = {
  project_id: 'project:test',
  source_id: 'source:p203',
  source_title: 'Page_007_P203.pdf',
  enabled: true,
  status: 'ready',
  stale: false,
  point_count: 7,
  current_file_hash: 'abc',
}

describe('ChatDrawingRetrievalControls', () => {
  beforeEach(() => {
    listSources.mockReset()
    enableSource.mockReset()
    rebuildSource.mockReset()
    useDrawingRetrievalStore.setState({
      request: {
        projectId: null,
        mode: 'existing',
        selectedSourceIds: [],
        resultLimit: 3,
      },
      debugByMessageId: {},
      pendingDebug: null,
    })
  })

  it('selects ready included sources and enables visual modes', async () => {
    listSources.mockResolvedValue({
      project_id: 'project:test',
      sources: [readySource],
    })

    render(
      <ChatDrawingRetrievalControls
        projectId="project:test"
        includedSourceIds={['source:p203']}
      />
    )

    fireEvent.click(await screen.findByText(/Sources ·/))
    const source = await screen.findByLabelText('Use Page_007_P203.pdf')
    await waitFor(() => expect(source).toBeChecked())

    const multiVector = screen.getByRole('button', { name: 'Multi-vector' })
    expect(multiVector).toBeEnabled()
    fireEvent.click(multiVector)

    expect(useDrawingRetrievalStore.getState().request.mode).toBe('multi_vector')
    expect(useDrawingRetrievalStore.getState().request.selectedSourceIds).toEqual([
      'source:p203',
    ])
  })

  it('disables visual modes and indexes an eligible PDF', async () => {
    listSources.mockResolvedValue({
      project_id: 'project:test',
      sources: [
        {
          ...readySource,
          enabled: false,
          status: 'disabled',
          point_count: 0,
        },
      ],
    })
    enableSource.mockResolvedValue({
      ...readySource,
      status: 'queued',
      point_count: 0,
    })

    render(
      <ChatDrawingRetrievalControls
        projectId="project:test"
        includedSourceIds={['source:p203']}
      />
    )

    expect(await screen.findByRole('button', { name: 'Multi-vector' })).toBeDisabled()
    fireEvent.click(screen.getByText(/Sources ·/))
    fireEvent.click(screen.getByRole('button', { name: 'Index' }))

    await waitFor(() => {
      expect(enableSource).toHaveBeenCalledWith('project:test', 'source:p203')
    })
  })

  it('does not allow an indexed source excluded from chat context', async () => {
    listSources.mockResolvedValue({
      project_id: 'project:test',
      sources: [readySource],
    })

    render(
      <ChatDrawingRetrievalControls
        projectId="project:test"
        includedSourceIds={[]}
      />
    )

    fireEvent.click(await screen.findByText(/Sources ·/))
    expect(await screen.findByLabelText('Use Page_007_P203.pdf')).toBeDisabled()
    expect(screen.getByText(/Excluded from chat context/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Compare' })).toBeDisabled()
  })
})
