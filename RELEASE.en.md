# DSH Memory 1.0.0 release notes

Released 2026-11-04. Package: `@local/dsh-memory`. Tag: `v1.0.0`.

This release prepares the local beta implementation for its first complete public delivery: active submission, explicit capture, budgeted recall, same-call compaction, global/project scopes, review candidates, relationship browsing and optional knowledge-base sharing. Public version and display names are updated while historical storage and preset IDs remain compatible.

Deliverables include the plugin archive, source, bilingual README, project history, guides and release notes, a changelog, checksums and per-file inventory. The archive bundles Python source, not the interpreter or NumPy. Exact host requirements are declared in `plugin/package.json`; compatibility is not widened to untested versions.

Release checks use public synthetic tests, JavaScript syntax checks, package inspection and a publication scan. Results are recorded in `release-manifest.json`. No live cloud-model evaluation or private-memory test is performed for publication. Compatibility with every third-party plugin and platform is not established.

Back up your memory directory before upgrading from beta, install the new package through the DSH plugin manager and restart if requested. There is no automatic updater, implicit data migration or cross-device synchronization.
