# DSH Memory 1.0.8

This release consolidates changes since public 1.0.5 and the November 7, 2026 submission-retry and graph-label fixes.

- A dispatched submission consumes its immutable answer even when rejected. The next step exposes a fresh contract instead of reusing that batch when the request is unchanged. Stale calls also refresh the contract. Source checks, session ownership and first-response immutability remain enforced.
- Path validation hints distinguish a literal path from the full rule and its conditions. Only state=saved with can_confirm_saved=true confirms a save. Restarting does not establish that a model has retried or saved a pending memory.
- Graph labels keep a fixed offset from their nodes. Occluded labels blur and clear again when uncovered. Removed label relocation and leader lines; rotation, zoom and selection remain available.
- One automatic runtime follows agents across preset and tool realms. The pure preset, memoryEnabled=false sessions and excludedPresets skip memory injection, collection, tool binding and augmented compaction. Existing records remain intact.
- Optional WeChat conversation scopes and project style-profile storage isolate chats. Style profiles are identified as model inference rather than global facts and require a compatible WeChat plugin. This package contains no WeChat client or model training.

Compatibility follows package.json peerDependencies: DSH and related official packages 0.2.1-rc.5, Cordis ~4.0.5. Older hosts are not guaranteed compatible.

Release checks use synthetic data and isolated local Python workers for corrected retries, immutable old answers, pure exclusion, conversation isolation and tool continuation, plus JavaScript syntax, archive round-trip and publication scans. No private memory database, real chat or paid model was used. A full installed-host restart of this release and a visual acceptance check of the graph were not performed. Exact build identity, digest and test counts are in release-manifest.json.

Install local-dsh-memory-1.0.8.tgz through the DSH plugin manager. Save your work, fully exit the Host including its tray process, reopen it and confirm version 1.0.8 in Memory details. Retry failed memories in the original conversation and inspect both successful tool receipts and stored entries; an assistant's verbal acknowledgment is insufficient.
