# DSH Memory 1.0.9

Fix slow entry into memory management: the local list no longer waits for knowledge-library synchronization. It returns immediately, while complete linked snapshots appear afterward. Loading status is visible and local entries remain usable when the linked service fails.

The management-only loader coalesces concurrent requests per session, retains at most eight session snapshots and expires completed snapshots after thirty seconds. Provider notifications and replacement invalidate cached and in-flight results. The frontend coalesces refreshes and preserves unchanged list identity. Conversation recall still reads fresh snapshots.

Validation: an isolated browser page with synthetic records and a fixed three-second linked-service delay displayed local records in 96 ms versus 3489 ms before the change. This is one measurement of that scenario, not a live-host speed guarantee. Linked records later appeared, project scope switching passed and no page runtime errors occurred. New checks cover coalescing, session isolation, invalidation, expiry, offline/incomplete snapshots and provider removal; existing release regressions and archive/publication checks remain enabled. No private database, chat or machine-specific test materials are published. Performance after installing and fully restarting the live Host remains unverified.

Compatibility is unchanged from 1.0.8; see package.json peerDependencies. Install local-dsh-memory-1.0.9.tgz through the DSH plugin manager, fully exit including the tray process, reopen and confirm version 1.0.9 in Memory details. Build identity, digest and test counts are recorded in release-manifest.json.
