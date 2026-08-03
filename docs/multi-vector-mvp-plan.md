# Multi-Vector Drawing Retrieval MVP

This document tracks the isolated experiment for adding optional multi-vector visual retrieval to Construction OS.

## Safety rules

- Work only in `YourIndieDev/construction-os-multi-vector` on the `multi-vector` branch.
- Keep the existing SurrealDB extraction and retrieval paths unchanged.
- Run Qdrant and the embedding model as optional services.
- Multi-vector failures must never block normal source ingestion or chat.
- Do not merge this experiment into the original Construction OS repository until evaluation is complete.
- Use targeted local tests for this MVP; GitHub Actions CI is not required.

## Phase 0: Baseline and isolation

- [x] Create `multi-vector` branch from `main`.
- [x] Add this implementation tracker.
- [x] Open a draft PR for implementation visibility.
- [x] Confirm CI workflows are intentionally out of scope for this MVP.
- [x] Confirm the experimental Docker stack runs independently on the target laptop.
- [x] Confirm one architectural PDF can be uploaded, extracted, and queried using existing retrieval.

## Phase 1: Qdrant infrastructure

- [x] Add optional Qdrant Docker service and persistent volume.
- [x] Add local-only port binding and readiness health endpoint.
- [x] Add Qdrant environment configuration.
- [x] Add lightweight Qdrant connection helper using the existing HTTP client.
- [x] Add Qdrant health API.
- [x] Add tests for configuration and graceful unavailability.
- [x] Run targeted backend tests and configuration validation: 5 tests passed.
- [x] Confirm the Docker stack and Qdrant health work end to end on the target laptop.

## Phase 2: ColSmol embedding service

- [x] Add isolated GPU model service.
- [x] Add image and query embedding endpoints.
- [x] Add model cache volume and health reporting.
- [x] Add service and app integration contract tests.
- [x] Run targeted app and service contract tests.
- [x] Verify multi-vector query and image output shape.
- [x] Verify RTX 5050 8 GB execution.
- [x] Confirm real query output: 12 vectors with dimension 128 using `vidore/colSmol-256M`.

## Phase 3: Qdrant collection and storage

- [x] Create versioned multi-vector collection implementation.
- [x] Configure cosine distance with the MaxSim comparator and payload indexes.
- [x] Add page/crop metadata schema with deterministic point IDs.
- [x] Add source-scoped delete, exact count, upsert, and rebuild behavior.
- [x] Add storage tests: 7 tests pass in isolated mocked validation.
- [x] Add an idempotent collection initialization API.
- [x] Run targeted storage tests in the application environment.
- [x] Initialize and validate the real Qdrant collection on the target laptop.

## Phase 4: Source opt-in and status

- [x] Add persisted project/source indexing state without modifying core source ingestion.
- [x] Add enable, disable, status, project-list, and rebuild APIs.
- [x] Add current-file hash comparison and stale-file detection.
- [x] Add isolated `/multivector` UI status and manual controls.
- [x] Add a visible project-header `Visual index` dialog with multi-select enable, disable, and rebuild controls.
- [x] Add backend state tests and frontend control tests.
- [x] Restore the project source-status listing helper used by the normal UI and retrieval filters.
- [ ] Run the updated project visual-index frontend test on the target laptop.
- [ ] Verify multi-select disable and rebuild with real project sources. Enable and live status were verified with P203.

## Phase 5: Indexing job

- [x] Reuse completed drawing page, grid-crop, and region-crop assets when available.
- [x] Render page and grid-crop assets directly when drawing extraction assets are unavailable.
- [x] Embed selected images one at a time through the GPU ColSmol service.
- [x] Publish each image multi-vector and metadata payload to Qdrant.
- [x] Track queued, indexing, ready, error, point-count, progress, and retry/rebuild state.
- [x] Keep normal drawing extraction independent.
- [x] Add targeted worker, two-source isolation, and UI polling tests.
- [x] Add `scripts/verify-phase5.ps1` for sequential unattended build, tests, real indexing, disable, re-enable, rebuild, health checks, and local reports.
- [ ] Run the unattended Phase 5 verifier on the target laptop; manual UI verification was used instead because of harness-specific PowerShell issues.
- [x] Verify one real PDF reaches `ready` with a Qdrant point count greater than zero: P203 reached `ready` with 7 points.
- [x] Retain automated two-source isolation coverage because only one real source was available.

## Phase 6: Multi-vector retrieval

- [x] Add a validated ColSmol query-embedding client using the same model service.
- [x] Add Qdrant MaxSim query support with project, ready-source, and optional asset filters.
- [x] Exclude disabled, stale, unindexed, and error sources before Qdrant search.
- [x] Deduplicate page and crop overlaps by retaining the highest-scoring hit per source page.
- [x] Return the existing `EvidenceItem` and Search API result shape with visual metadata.
- [x] Add isolated `/drawing-extractions/multivector/search` API.
- [x] Add query-client, Qdrant-filter, ready-source, deduplication, evidence, and API tests.
- [x] Add gated `scripts/verify-phase6.ps1`; it requires a passing Phase 5 report.
- [ ] Run the full Phase 6 unit and regression suite in the application container on the target laptop.
- [x] Verify a real ColSmol query returns filtered Qdrant evidence with images and unique source/page pairs: P203 returned one result from 7 indexed points.

## Phase 7: Retrieval modes

- [x] Add `existing`, `multi_vector`, and `compare` modes through an isolated retrieval-mode orchestrator and API.
- [x] Preserve existing retrieval as the default and as fallback for failed or empty multi-vector requests.
- [x] Record separate rankings, timings, thresholds, and score spaces without score fusion.
- [x] Keep the Phase 6 multi-vector search endpoint unchanged for backward compatibility.
- [x] Add unit and API contract tests for default behavior, comparison, fallback, timing, source forwarding, and independent thresholds.
- [x] Verify a real comparison request on the target laptop: existing retrieval completed with zero matches, while multi-vector returned one P203 crop with no backend errors.
- [x] Repair legacy crop-name metadata at retrieval time so existing Qdrant points report the original PDF source without requiring re-indexing.

## Phase 8: Chat integration

- [x] Add an experimental streaming project-chat endpoint with `existing`, `multi_vector`, and `compare` request modes.
- [x] Attach Qdrant-retrieved crops and their parent page images to the current project chat agent as request-scoped multimodal inputs.
- [x] Limit retrieval to three unique source/page results and six deduplicated images.
- [x] Confine image paths to drawing-extraction storage, reject invalid files, cap encoded bytes, and downscale oversized images.
- [x] Include source title, sheet number, page, crop bounds, rank, and visual score in guarded text context.
- [x] Preserve the existing system prompt, skills, collections, native tools, MCP tools, artifact templates, HTML templates, A2UI, session security, and normal chat fallback.
- [x] Add conservative vision-model capability checks and text-only retry for multimodal compatibility failures.
- [x] Emit sanitized `drawing_retrieval_debug` metadata and retain it per assistant message for Phase 9.
- [x] Keep retrieval settings one-turn only so ordinary later chat requests return to `existing` behavior.
- [x] Add unit, graph, API, source-isolation, payload, model-capability, and tool-loop regression tests.
- [x] Run the targeted Phase 8 test suite on the target laptop: 47 tests passed.
- [ ] Verify a real P203 visual chat answer on the target laptop; retrieval and debug events passed, but the configured `gemini-2.5-flash-lite` chat model returned a provider 404 and must be replaced with an available vision model.

## Phase 9: Chat UI controls

- [x] Add an experimental `Existing`, `Multi-vector`, and `Compare` retrieval selector to project chat.
- [x] Add a project-source selector with ready, stale, queued, indexing, disabled, and error states.
- [x] Disable visual modes when no ready source is selected or when a source is excluded from chat context.
- [x] Add inline enable/index and rebuild actions with polling progress and error display.
- [x] Route only visual-mode messages through the isolated Phase 8 endpoint while keeping ordinary chat requests unchanged.
- [x] Show the retrieval method on every new assistant response, including a compact existing-retrieval marker.
- [x] In compare mode, show separate existing and multi-vector rankings, top sheets, scores, result counts, errors, and retrieval times.
- [x] Add a collapsible retrieved-evidence section with authenticated crop previews and links to full drawing pages.
- [x] Restore per-message visual evidence metadata when a chat session is reopened.
- [x] Add backend path-security, debug-persistence, ranking-summary, transport, event-binding, controls, and evidence-panel tests.
- [ ] Run the targeted Phase 9 backend and frontend test suites on the target laptop.
- [ ] Verify the complete Phase 9 flow in the local browser with P203: choose mode, select source, submit chat question, inspect crop, and open the full page.

## Phase 10: Evaluation

- [ ] Create benchmark questions and expected evidence.
- [ ] Compare retrieval accuracy, final answers, latency, and GPU use.
- [ ] Export results.
- [ ] Test a held-out drawing set.
- [ ] Produce a final recommendation.
