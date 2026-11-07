# DSH Memory 1.0.11

Long-term memory for DeepSeek Harness. Capture reusable preferences, constraints and project facts with their sources, then recall relevant evidence in later turns. Records support correction, withdrawal, manual management and optional knowledge-base integration.

[English](README.md) · [简体中文](README.zh-CN.md)

## Product and project references

- [Project and evolution record](PROJECT-RECORD.en.md): goals, architecture, development stages and next steps.
- [User guide](GUIDE.en.md): installation, configuration, scopes, integration and troubleshooting.
- [Release notes](RELEASE.en.md): the 1.0.11 deliverable, compatibility and validation limits.
- [Changelog](CHANGELOG.md): public release history.

## Current release

The current public release is **1.0.11**, packaged as `@local/dsh-memory`. It consolidates the local beta implementation while retaining storage and preset identifiers for continuity. The version number does not establish perfect extraction accuracy or compatibility with every DSH release.

## Download

- [Gitee download](https://gitee.com/KingsleyAsher/DSH-Memory/raw/main/dist/local-dsh-memory-1.0.11.tgz)
- [GitCode download](https://api.gitcode.com/api/v5/repos/KingsleyAsher/DSH-Memory/raw/dist/local-dsh-memory-1.0.11.tgz?ref=main)

All three sources are checked concurrently. The newest release wins, with regional-source preference and download fallback. Mirrors can lag.

- [Release 1.0.11](https://github.com/KingsleyAsher/DSH-Memory/releases/tag/v1.0.11)
- [Plugin package](https://github.com/KingsleyAsher/DSH-Memory/releases/download/v1.0.11/local-dsh-memory-1.0.11.tgz)
- [Repository download](dist/local-dsh-memory-1.0.11.tgz) · [SHA-256 checksums](dist/SHA256SUMS)

## What the plugin does

- **Capture:** the conversation model proposes records through `memory_submit`; program checks enforce source bindings, scope and state transitions. Explicit requests also have a deterministic capture path.
- **Recall:** relevant project and global evidence is retrieved before an agent step under a shared budget, rather than injecting the entire store.
- **Compaction:** supported official Basic compaction engines produce the continuation summary and memory in the existing model call. Custom engines need a dedicated adapter.
- **Management:** browse lists and a relationship view, add or delete records, and accept, edit or reject uncertain candidates. A graph connection is not proof of a factual relationship.
- **Scopes:** all Agent presets share the same global and project memory store. Global records apply across projects; project records activate only in their corresponding project. Switching presets, windows or projects does not delete records; explicit clearing does.
- **Optional sharing:** compatible installed components share records when connected. The plugin works independently without them. Knowledge-base records remain read-only and follow their source permissions.

## Install

Declared compatibility is DSH **0.2.1-rc.5** and Cordis **~4.0.5**. Python **3.11+** with NumPy is required; the validated host environment uses Node 24. Install the Python dependency in the interpreter used by the plugin:

```sh
python -m pip install numpy
```

Add this installation source in the DSH plugin manager, or choose the downloaded local `.tgz`:

```text
https://raw.githubusercontent.com/KingsleyAsher/DSH-Memory/main/dist/local-dsh-memory-1.0.11.tgz
```

Enable the plugin and open Memory in the sidebar, under More in narrow layouts, or through the conversation view. If the host asks for a restart, quit the tray process as well. Memory attaches to supported presets as agents are created or resumed; a separate DSH Memory preset remains available.

## Data and privacy

Runtime data stays in the user's local SQLite store. Recalled evidence is passed to the current conversation model: a cloud model receives that evidence as part of its context. The plugin does not start a separate extraction model, download models automatically or enable background cloud embedding requests.

Published files exclude the developer's memories, chats, knowledge-base contents, credentials, machine paths, logs and research-run data. See [publication boundaries](PUBLICATION.md).

## Verification and limits

Synthetic tests cover scope lifecycle, candidate review and explicit capture. Package contents and hashes are recorded in the [release manifest](release-manifest.json). Earlier integration checks used an isolated worker and synthetic knowledge sources; they do not establish accuracy on private material or long-running daily use.

Attachment extraction is outside this plugin. Custom compactors, complex cross-project references and arbitrary context lengths are not universally supported. Pending work persists after shutdown, but no inference runs without a host. [Update rules](VERSIONING.en.md) automatically install all newer versions, including major upgrades and preview switches. Status is inline, with no update popups. Cross-device synchronization is not provided.

## Source and build

```sh
python scripts/build_release.py
python -m unittest discover -s tests -p "test_*.py"
```

`plugin/src/` contains the host integration and UI; `memory_core/` implements persistence, source validation and recall. Packaging reads only the public source tree. The project uses the repository's existing [MIT license](LICENSE).

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
