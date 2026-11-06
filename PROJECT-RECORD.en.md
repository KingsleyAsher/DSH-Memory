# Project and evolution record

## Purpose

This project turns reusable conversational information into traceable, updatable memory. The model makes semantic proposals; code enforces source bindings, scope, current validity, transactions and recovery. Stored text is not automatically a current fact: corrections and withdrawals must affect subsequent recall.

## Engineering stages

These stages describe the implementation lineage, not a claim that each internal experiment was a public release.

1. **Independent core:** SQLite sources and facts, text retrieval, exclusion, deletion and revision, with raw input separated from derived representations.
2. **Evidence and state:** atomic records, source references, entity/event identity and a ledger for targeted additions, retention, replacement and withdrawal.
3. **Unified admission:** active tool submissions and compaction output use shared contracts and commit checks. Pending and failed work persists, with bounded replay and stale-source rejection.
4. **DSH integration:** a private Python worker, capture tools, budgeted pre-step recall and a same-call adapter for official Basic compaction.
5. **Manageable memory:** global/project scopes, manual entries, review candidates, a relationship view and explicit capture, followed by client discovery and ordinary preset attachment fixes.
6. **Optional knowledge channel:** read-only source snapshots and a global-memory bridge reuse one authoritative store while retaining standalone behavior and permissions.
7. **Public 1.0.0 preparation, 2026-11-04:** consistent package identity, bilingual documentation, an allowlisted build and checksums; private runtime data and internal research outputs are excluded. The existing repository MIT license is retained.

## Source map

| Layer | Location | Responsibility |
| --- | --- | --- |
| Host integration | `plugin/src/ui.js`, `runtime.js`, `index.js` | Presets, tools, events and compaction |
| Worker bridge | `plugin/src/store.js`, `bridge.js` | Shared service, private stdio and authenticated management |
| UI | `plugin/src/client.js` | Entries, review and relationship view |
| Optional knowledge | `plugin/src/knowledge-memory.js` | Source snapshots and validity checks |
| Core | `memory_core/` | Provenance, contracts, state, budgets, retrieval and persistence |
| Release tooling | `scripts/build_release.py` | Allowlisted packaging, digests and publication scans |

## Remaining work

Internal small-sample extraction results are not published as product accuracy. Private data is not released as a reproduction dataset. Further work includes broader synthetic end-to-end evaluations, host lifecycle verification, custom-compactor support and measured long-term recall quality and overhead. Graphs, caches and multiple representations do not independently establish large-library retrieval performance.

## 1.0.8: memory during tool continuation (2026-11-05)

Use the real user task in session history to prevent empty recall snapshots after tools return. Re-query each step so deletion and withdrawal remain visible. Synthetic continuation and persisted-worker checks complement the existing release checks; the 1.0.4 details page, receipts and shared scopes remain. No private-user data or real-model action was verified; see the release notes.

## 1.0.8 changes and limits

This release consolidates changes since public 1.0.5 and the November 7, 2026 submission-retry and graph-label fixes.

- A dispatched submission consumes its immutable answer even when rejected. The next step exposes a fresh contract instead of reusing that batch when the request is unchanged. Stale calls also refresh the contract. Source checks, session ownership and first-response immutability remain enforced.
- Path validation hints distinguish a literal path from the full rule and its conditions. Only state=saved with can_confirm_saved=true confirms a save. Restarting does not establish that a model has retried or saved a pending memory.
- Graph labels keep a fixed offset from their nodes. Occluded labels blur and clear again when uncovered. Removed label relocation and leader lines; rotation, zoom and selection remain available.
- One automatic runtime follows agents across preset and tool realms. The pure preset, memoryEnabled=false sessions and excludedPresets skip memory injection, collection, tool binding and augmented compaction. Existing records remain intact.
- Optional WeChat conversation scopes and project style-profile storage isolate chats. Style profiles are identified as model inference rather than global facts and require a compatible WeChat plugin. This package contains no WeChat client or model training.

Compatibility follows package.json peerDependencies: DSH and related official packages 0.2.1-rc.5, Cordis ~4.0.5. Older hosts are not guaranteed compatible.

Release checks use synthetic data and isolated local Python workers for corrected retries, immutable old answers, pure exclusion, conversation isolation and tool continuation, plus JavaScript syntax, archive round-trip and publication scans. No private memory database, real chat or paid model was used. A full installed-host restart of this release and a visual acceptance check of the graph were not performed. Exact build identity, digest and test counts are in release-manifest.json.

Install local-dsh-memory-1.0.8.tgz through the DSH plugin manager. Save your work, fully exit the Host including its tray process, reopen it and confirm version 1.0.8 in Memory details. Retry failed memories in the original conversation and inspect both successful tool receipts and stored entries; an assistant's verbal acknowledgment is insufficient.

## 1.0.9 loading improvement

Fix slow entry into memory management: the local list no longer waits for knowledge-library synchronization. It returns immediately, while complete linked snapshots appear afterward. Loading status is visible and local entries remain usable when the linked service fails.

The management-only loader coalesces concurrent requests per session, retains at most eight session snapshots and expires completed snapshots after thirty seconds. Provider notifications and replacement invalidate cached and in-flight results. The frontend coalesces refreshes and preserves unchanged list identity. Conversation recall still reads fresh snapshots.

Validation: an isolated browser page with synthetic records and a fixed three-second linked-service delay displayed local records in 96 ms versus 3489 ms before the change. This is one measurement of that scenario, not a live-host speed guarantee. Linked records later appeared, project scope switching passed and no page runtime errors occurred. New checks cover coalescing, session isolation, invalidation, expiry, offline/incomplete snapshots and provider removal; existing release regressions and archive/publication checks remain enabled. No private database, chat or machine-specific test materials are published. Performance after installing and fully restarting the live Host remains unverified.

Compatibility is unchanged from 1.0.8; see package.json peerDependencies. Install local-dsh-memory-1.0.9.tgz through the DSH plugin manager, fully exit including the tray process, reopen and confirm version 1.0.9 in Memory details. Build identity, digest and test counts are recorded in release-manifest.json.

## 1.0.10 host compatibility

Fix plugin admission after DSH upgrades. Required DSH packages now accept the 0.2.1 series from rc.5 and the 0.2.2 series from rc.1. Cordis accepts ~4.0.5 or ~4.1.0. DSH 0.2.3 and Cordis 4.2 are not automatically admitted.

Isolated checks use official 0.2.1-rc.5 / Cordis 4.0.5 modules and the installed 0.2.2-rc.1 / Cordis 4.1.0 archive. Both exercise plugin loading, the real Agent tool loop, persistence, same-call compaction, cross-session recall, project isolation, worker restart and pending-work recovery. Model output is an offline fixture, not a paid or real-model evaluation. The newer host fixture loads its required native tool executor normally; the memory plugin does not replace the user's executor.

The data directory and database format remain unchanged. Existing memories, pure exclusion, strict save receipts and progressive management-page loading are preserved. A reusable dual-host test is included. See release-manifest.json for exact checks and archive identity. Full desktop-process restart and live activation remain to be confirmed.

Install local-dsh-memory-1.0.10.tgz through the DSH plugin manager, fully exit including the tray process, reopen and confirm 1.0.10 in Memory details. The fix uses supported dependency declarations instead of bypassing Host compatibility checks.
