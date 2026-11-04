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
