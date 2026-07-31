import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ProjectMultiVectorDialog } from './ProjectMultiVectorDialog'

describe('ProjectMultiVectorDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('loads project sources and starts visual indexing for selected PDFs', async () => {
    const sourceList = {
      project_id: 'project:test',
      sources: [
        {
          project_id: 'project:test',
          source_id: 'source:plans',
          source_title: 'Architectural Plans',
          enabled: false,
          status: 'disabled',
          stale: false,
          point_count: 0,
          current_file_hash: 'abc123',
        },
      ],
    }
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => sourceList,
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          project_id: 'project:test',
          source_id: 'source:plans',
          source_title: 'Architectural Plans',
          enabled: true,
          status: 'queued',
          stale: false,
          point_count: 0,
          current_file_hash: 'abc123',
        }),
      })
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          ...sourceList,
          sources: [{ ...sourceList.sources[0], enabled: true, status: 'indexing' }],
        }),
      })

    vi.stubGlobal('fetch', fetchMock)

    render(
      <ProjectMultiVectorDialog
        open
        onOpenChange={vi.fn()}
        projectId="project:test"
        projectName="Test Project"
      />
    )

    const sourceCheckbox = await screen.findByLabelText('Select Architectural Plans')
    fireEvent.click(sourceCheckbox)
    fireEvent.click(screen.getByRole('button', { name: 'Enable and index selected' }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/drawing-extractions/multivector/projects/project%3Atest/sources/source%3Aplans/enable',
        { method: 'POST' }
      )
    })
  })

  it('disables selection for sources without uploaded PDF files', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          project_id: 'project:test',
          sources: [
            {
              project_id: 'project:test',
              source_id: 'source:text',
              source_title: 'Text source',
              enabled: false,
              status: 'disabled',
              stale: false,
              point_count: 0,
              current_file_hash: null,
              file_error: 'Source has no uploaded file',
            },
          ],
        }),
      })
    )

    render(
      <ProjectMultiVectorDialog
        open
        onOpenChange={vi.fn()}
        projectId="project:test"
      />
    )

    const sourceCheckbox = await screen.findByLabelText('Select Text source')
    expect(sourceCheckbox).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Enable and index selected' })).toBeDisabled()
  })
})
