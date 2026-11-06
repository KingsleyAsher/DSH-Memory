# DSH Memory 1.0.10

Fix plugin admission after DSH upgrades. Required DSH packages now accept the 0.2.1 series from rc.5 and the 0.2.2 series from rc.1. Cordis accepts ~4.0.5 or ~4.1.0. DSH 0.2.3 and Cordis 4.2 are not automatically admitted.

Isolated checks use official 0.2.1-rc.5 / Cordis 4.0.5 modules and the installed 0.2.2-rc.1 / Cordis 4.1.0 archive. Both exercise plugin loading, the real Agent tool loop, persistence, same-call compaction, cross-session recall, project isolation, worker restart and pending-work recovery. Model output is an offline fixture, not a paid or real-model evaluation. The newer host fixture loads its required native tool executor normally; the memory plugin does not replace the user's executor.

The data directory and database format remain unchanged. Existing memories, pure exclusion, strict save receipts and progressive management-page loading are preserved. A reusable dual-host test is included. See release-manifest.json for exact checks and archive identity. Full desktop-process restart and live activation remain to be confirmed.

Install local-dsh-memory-1.0.10.tgz through the DSH plugin manager, fully exit including the tray process, reopen and confirm 1.0.10 in Memory details. The fix uses supported dependency declarations instead of bypassing Host compatibility checks.
