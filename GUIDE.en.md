# DSH Memory user guide

## First use

Install the dependencies and package described in the README, then enable the plugin. Add a disposable global record through Memory, confirm it appears and delete it. In a conversation, ask explicitly to remember a preference. A successful save receipt or an actual stored record is the criterion; a model's verbal promise alone is insufficient.

## Scope lifecycle

Global records cover preferences and constraints that apply across projects. Project records belong to the current window's project and can be used by its sessions. Switching or clearing that window's project deletes the corresponding project records, sources and derived views. Other windows retain their own project scopes. Keep permanent project archives as documents elsewhere.

The main model marks automatic records as global or project; ambiguous scope defaults to project. Global records retain a minimal independent evidence archive. Deletion is not a recoverable trash operation. A package upgrade does not itself erase storage, but normal project lifecycle rules still apply.

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
