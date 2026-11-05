# DSH Memory 1.0.5

Long-term memory for DeepSeek Harness. Capture reusable preferences, constraints and project facts with their sources, then recall relevant evidence in later turns. Records support correction, withdrawal, manual management and optional knowledge-base integration.

[English](README.md) · [简体中文](README.zh-CN.md)

## Product and project references

- [Project and evolution record](PROJECT-RECORD.en.md): goals, architecture, development stages and next steps.
- [User guide](GUIDE.en.md): installation, configuration, scopes, integration and troubleshooting.
- [Release notes](RELEASE.en.md): the 1.0.5 deliverable, compatibility and validation limits.
- [Changelog](CHANGELOG.md): public release history.

## Current release

The current public release is **1.0.5**, packaged as `@local/dsh-memory`. It consolidates the local beta implementation while retaining storage and preset identifiers for continuity. The version number does not establish perfect extraction accuracy or compatibility with every DSH release.

## Download

- [Gitee download](https://gitee.com/KingsleyAsher/DSH-Memory/raw/main/dist/local-dsh-memory-1.0.5.tgz)
- [GitCode download](https://api.gitcode.com/api/v5/repos/KingsleyAsher/DSH-Memory/raw/dist/local-dsh-memory-1.0.5.tgz?ref=main)

All three sources are checked concurrently. The newest release wins, with regional-source preference and download fallback. Mirrors can lag.

- [Release 1.0.5](https://github.com/KingsleyAsher/DSH-Memory/releases/tag/v1.0.5)
- [Plugin package](https://github.com/KingsleyAsher/DSH-Memory/releases/download/v1.0.5/local-dsh-memory-1.0.5.tgz)
- [Repository download](dist/local-dsh-memory-1.0.5.tgz) · [SHA-256 checksums](dist/SHA256SUMS)

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
https://raw.githubusercontent.com/KingsleyAsher/DSH-Memory/main/dist/local-dsh-memory-1.0.5.tgz
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
