export type DrawingRetrievalMode = 'existing' | 'multi_vector' | 'compare'

export interface DrawingRetrievalRankingResult {
  id?: string | null
  source_id?: string | null
  parent_id?: string | null
  source_title?: string | null
  title?: string | null
  sheet_number?: string | null
  page_number?: number | null
  score?: number | null
  similarity?: number | null
  rank?: number | null
}

export interface DrawingRetrievalRankingDebug {
  result_count: number
  duration_ms?: number | null
  score_space?: string | null
  retrieval_mode_used?: string | null
  error?: string | null
  results?: DrawingRetrievalRankingResult[]
}

export interface DrawingVisualEvidenceDebug {
  rank: number
  source_id: string
  source_title: string
  sheet_number?: string | null
  sheet_title?: string | null
  page_number: number
  page_index?: number
  asset_kind: string
  score: number
  bbox_norm?: Record<string, number> | null
  crop_path: string
  parent_page_path?: string | null
  qdrant_point_id?: string | null
}

export interface DrawingVisionDebug {
  model_id?: string | null
  model_name?: string | null
  provider?: string | null
  supported?: boolean
  reason?: string | null
  image_count?: number
}

export interface DrawingRetrievalDebug {
  message_id?: string | null
  requested_mode: DrawingRetrievalMode
  mode_used: DrawingRetrievalMode | string
  project_id: string
  requested_source_ids: string[]
  existing?: DrawingRetrievalRankingDebug | null
  multi_vector?: DrawingRetrievalRankingDebug | null
  vision?: DrawingVisionDebug | null
  evidence: DrawingVisualEvidenceDebug[]
  fallback_reason?: string | null
}

export interface DrawingRetrievalRequestOptions {
  projectId: string | null
  mode: DrawingRetrievalMode
  selectedSourceIds: string[]
  resultLimit: number
}
