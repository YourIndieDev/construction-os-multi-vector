import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DrawingEvidencePanel } from './DrawingEvidencePanel'
import type { DrawingRetrievalDebug } from '@/lib/types/drawing-retrieval'

const fetchEvidence = vi.fn()

vi.mock('@/lib/api/drawing-extraction', () => ({
  drawingExtractionApi: {
    fetchMultiVectorEvidenceImage: (...args: unknown[]) => fetchEvidence(...args),
  },
}))

const debug: DrawingRetrievalDebug = {
  requested_mode: 'compare',
  mode_used: 'compare',
  project_id: 'project:test',
  requested_source_ids: ['source:p203'],
  existing: {
    result_count: 1,
    duration_ms: 835,
    score_space: 'native_existing_retrieval',
    retrieval_mode_used: 'vector',
    results: [
      {
        id: 'chunk:one',
        source_id: 'source:p203',
        sheet_number: 'P203',
        title: 'Page_007_P203.pdf - Page 1',
        score: 0.82,
      },
    ],
  },
  multi_vector: {
    result_count: 1,
    duration_ms: 729,
    score_space: 'qdrant_maxsim',
    retrieval_mode_used: 'multi_vector',
  },
  vision: {
    supported: true,
    model_name: 'gemini-2.5-flash',
    image_count: 2,
  },
  evidence: [
    {
      rank: 1,
      source_id: 'source:p203',
      source_title: 'Page_007_P203.pdf',
      sheet_number: 'P203',
      page_number: 1,
      asset_kind: 'grid_crop',
      score: 29.506403,
      crop_path: '/data/crop.png',
      parent_page_path: '/data/page.png',
    },
  ],
  fallback_reason: null,
}

describe('DrawingEvidencePanel', () => {
  beforeEach(() => {
    fetchEvidence.mockReset()
    fetchEvidence.mockResolvedValue(new Blob(['image'], { type: 'image/png' }))
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:phase9-image'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(window, 'open').mockImplementation(() => null)
  })

  it('shows both rankings, scores, timing, crop preview, and full-page link', async () => {
    render(<DrawingEvidencePanel debug={debug} />)

    expect(screen.getByText('Retrieved evidence')).toBeInTheDocument()
    expect(screen.getByText('Existing retrieval')).toBeInTheDocument()
    expect(screen.getByText('Multi-vector retrieval')).toBeInTheDocument()
    expect(screen.getByText(/835 ms/)).toBeInTheDocument()
    expect(screen.getByText(/729 ms/)).toBeInTheDocument()
    expect(screen.getAllByText(/P203/).length).toBeGreaterThan(0)

    const crop = await screen.findByAltText('Retrieved crop from P203')
    expect(crop).toHaveAttribute('src', 'blob:phase9-image')
    expect(fetchEvidence).toHaveBeenCalledWith('/data/crop.png')
    expect(fetchEvidence).toHaveBeenCalledWith('/data/page.png')

    const openPage = await screen.findByRole('button', {
      name: 'Open full drawing page',
    })
    fireEvent.click(openPage)
    expect(window.open).toHaveBeenCalledWith(
      'blob:phase9-image',
      '_blank',
      'noopener,noreferrer'
    )
  })
})
