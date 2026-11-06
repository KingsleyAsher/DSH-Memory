# DSH Memory user guide

## First use

Install the dependencies and package described in the README, then enable the plugin. Add a disposable global record through Memory, confirm it appears and delete it. In a conversation, ask explicitly to remember a preference. A successful save receipt or an actual stored record is the criterion; a model's verbal promise alone is insufficient.

## Scope lifecycle

Global records apply across projects; project records activate only for their project. All Agent presets share the same DSH memory store. Switching a preset, window or project does not erase records. Explicit project clearing removes its records while preserving global memory. Legacy window identifiers for the same project remain accessible; unrelated projects stay isolated.

For normal tool submissions the conversation model chooses global/project, defaulting to project when omitted. Explicit persistent instructions also have a deterministic phrase-based capture path. Manual additions use the selected scope. Source validation does not guarantee correct semantic scope classification. Adding a global record does not automatically merge a similar older project record. Deletion is not recoverable through a trash view.

## Management and review

Use the relationship view to explore and the list to find, inspect or delete records. Manual additions choose a scope and require no language-model call. Input limits are 4,000 characters, 16 sentence segments and 800 characters per segment.

The main model can propose valuable but uncertain candidates for review. They stay outside normal factual recall until accepted or edited and accepted. Rejection changes candidate status. Confidence is model self-assessment, not a calibrated probability, and not every ambiguous statement is guaranteed to become a candidate.

## Automatic processing

Model proposals pass source, scope and current-state checks. Relevant global and project evidence shares a 768-token recall budget. Without an available local tokenizer, a conservative UTF-8 byte bound is used, which can admit less text. Contracts and pending work consume additional context; 768 is not the total plugin overhead.

Supported Basic compactors emit a continuation summary and memory in one existing call. Contracts bind at most 24 sources each, with at most eight contracts per compaction. Exceeding the limit rejects that operation while preserving input. Custom compactors require an adapter. Unfinished work persists across shutdown; no hidden inference continues after the host exits.

## Configuration

The root `@local/dsh-memory/store` service accepts `python`, an absolute `stateDir`, and development-only `coreRoot`. Without `stateDir`, storage is `memory-beta-state` beneath the host's `baseDir`; otherwise it falls back to `storages/memory-beta-state` beneath `DSH_HOME` or the user's `.dsh` directory.

Historical internal names such as `memory-beta` remain for configuration continuity. Back up the entire data directory with the host closed before moving it. Avoid concurrent independent writers. Management uses the host's authenticated connection, not a public administration endpoint.

## Knowledge-base integration

Compatible knowledge-base plugins and clients can access the same global records through the authenticated bridge. Knowledge documents remain owned by their source system and appear as read-only records with provenance. Later snapshots reflect source edits, withdrawal and permissions.

The memory plugin operates independently when other components are absent. Installation alone is insufficient: the peer must implement `dsh-memory/v1` and the corresponding bridge and establish an authorized connection. Do not assume old knowledge-base releases implement it. Integration does not relax project isolation, create Markdown duplicates or provide cross-device cloud synchronization.

## Troubleshooting

- Missing entry: verify that the plugin is enabled and inspect More in narrow layouts.
- Worker failure: check that the configured Python can import NumPy.
- No automatic capture: check the preset's model/tool services and actual save receipts. Custom compaction needs its own adapter.
- Unavailable sharing: verify peer support, enabled state, running host and library authorization.
- Old version after upgrade: exit the tray process and restart when requested; do not delete storage.

Report versions, error text and a minimal synthetic reproduction. Do not upload private databases, conversation transcripts or credential-bearing configuration.

## Details and updates

Open Memory → Details for the running version, last check, published version, source status and all GitHub/Gitee/GitCode repository links. Manual checks share the automatic update flow: about 15 seconds after startup and every six hours, eligible updates are installed through the host manager. Offline checks do not hide local version information or falsely report that the current version is latest.

A proactive write may only be confirmed when state=saved and can_confirm_saved=true. Unsuccessful and partial submissions fail the tool; use the per-item correction hints and a fresh batch. A completed transaction does not establish a saved memory. These guards do not guarantee every model's future wording.

## 1.0.8: memory across tool continuations

Applicable agreements remain available after tools return. A tool-only step recalls against the latest real user task from session history while respecting deletion, withdrawal, project scope and task changes. Applicable user preferences should guide the plan and remaining actions; historical quotations are not new commands. Saving and recalling a preference do not prove that a model completed the requested action: check the resulting task or artifact.


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
