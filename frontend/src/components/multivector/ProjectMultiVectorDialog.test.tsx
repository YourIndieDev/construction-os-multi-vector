import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ProjectMultiVectorDialog } from './ProjectMultiVectorDialog'

const listMultiVectorProjectSources = vi.fn()
const enableMultiVectorSource = vi.fn()
const disableMultiVectorSource = vi.fn()
const rebuildMultiVectorSource = vi.fn()

vi.mock('@/lib/api/drawing-extraction', () => ({
  drawingExtractionApi: {
    listMultiVectorProjectSources: (...args: unknown[]) =>
      listMultiVectorProjectSources(...args),
    enableMultiVectorSource: (...args: unknown[]) => enableMultiVectorSource(...args),
    disableMultiVectorSource: (...args: unknown[]) => disableMultiVectorSource(...args),
    rebuildMultiVectorSource: (...args: unknown[]) => rebuildMultiVectorSource(...args),
  },
}))

describe('ProjectMultiVectorDialog', () => {
  beforeEach(() => {
    listMultiVectorProjectSources.mockReset()
    enableMultiVectorSource.mockReset()
    disableMultiVectorSource.mockReset()
    rebuildMultiVectorSource.mockReset()
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
    listMultiVectorProjectSources.mockResolvedValue(sourceList)
    enableMultiVectorSource.mockResolvedValue({
      project_id: 'project:test',
      source_id: 'source:plans',
      source_title: 'Architectural Plans',
      enabled: true,
      status: 'queued',
      stale: false,
      point_count: 0,
      current_file_hash: 'abc123',
    })

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
      expect(enableMultiVectorSource).toHaveBeenCalledWith('project:test', 'source:plans')
    })
  })

  it('disables selection for sources without uploaded PDF files', async () => {
    listMultiVectorProjectSources.mockResolvedValue({
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
    })

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
