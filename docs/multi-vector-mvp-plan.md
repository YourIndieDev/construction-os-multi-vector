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
- [ ] Run the updated project visual-index frontend test on the target laptop.
- [ ] Verify multi-select enable, disable, status, and queued rebuild with real project sources.

## Phase 5: Indexing job

- [ ] Reuse existing drawing page and crop assets.
- [ ] Embed selected images one at a time.
- [ ] Publish vectors and payloads to Qdrant.
- [ ] Track progress, retries, errors, and idempotency.
- [ ] Keep normal drawing extraction independent.
- [ ] Add tests.

## Phase 6: Multi-vector retrieval

- [ ] Embed chat query with the same model.
- [ ] Search Qdrant with MaxSim and project/source filters.
- [ ] Deduplicate overlapping image results.
- [ ] Return existing `EvidenceItem` format.
- [ ] Add isolated search API and tests.

## Phase 7: Retrieval modes

- [ ] Add `existing`, `multi_vector`, and `compare` modes.
- [ ] Preserve existing retrieval as the default and fallback.
- [ ] Record rankings and timings without mixing scores.
- [ ] Add tests.

## Phase 8: Chat integration

- [ ] Attach retrieved visual evidence to the current chat agent.
- [ ] Limit and deduplicate image inputs.
- [ ] Include source and sheet metadata.
- [ ] Preserve existing tools, skills, and prompts.
- [ ] Add tests.

## Phase 9: Chat UI controls

- [ ] Add retrieval mode selector.
- [ ] Add indexed-source selector and readiness status.
- [ ] Show retrieved image evidence and comparison results.
- [ ] Mark controls experimental.
- [ ] Add frontend tests.

## Phase 10: Evaluation

- [ ] Create benchmark questions and expected evidence.
- [ ] Compare retrieval accuracy, final answers, latency, and GPU use.
- [ ] Export results.
- [ ] Test a held-out drawing set.
- [ ] Produce a final recommendation.
