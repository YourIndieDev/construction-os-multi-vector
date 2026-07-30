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
- [ ] Confirm the experimental Docker stack runs independently on the target laptop.
- [ ] Confirm one architectural PDF can be uploaded, extracted, and queried using existing retrieval.

## Phase 1: Qdrant infrastructure

- [x] Add optional Qdrant Docker service and persistent volume.
- [x] Add local-only port binding and readiness health endpoint.
- [x] Add Qdrant environment configuration.
- [x] Add lightweight Qdrant connection helper using the existing HTTP client.
- [x] Add Qdrant health API.
- [x] Add tests for configuration and graceful unavailability.
- [x] Run targeted backend tests and configuration validation: 5 tests passed.
- [ ] Confirm the Docker stack works end to end on the target laptop.

## Phase 2: ColSmol embedding service

- [ ] Add isolated GPU model service.
- [ ] Add image and query embedding endpoints.
- [ ] Add model cache volume and health reporting.
- [ ] Verify multi-vector output shape.
- [ ] Verify RTX 5050 8 GB execution.
- [ ] Add service contract tests.

## Phase 3: Qdrant collection and storage

- [ ] Create versioned multi-vector collection.
- [ ] Configure MaxSim and payload indexes.
- [ ] Add page/crop metadata schema.
- [ ] Add source-scoped delete and rebuild behavior.
- [ ] Add storage tests.

## Phase 4: Source opt-in and status

- [ ] Add persisted source-level indexing state.
- [ ] Add enable, disable, status, and rebuild APIs.
- [ ] Add stale-file detection.
- [ ] Add UI status and manual indexing controls.
- [ ] Add tests.

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
