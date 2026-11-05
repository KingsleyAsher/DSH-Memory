# DSH Memory 1.0.5

Fix memory continuation after tool calls. DSH pre-step input contains only newly claimed messages; a tool-only continuation could replace recalled preferences with an empty evidence snapshot. Recall now uses the latest genuine user task from session history and queries current memory again at every step. User-role messages from other plugins cannot replace that task. Deletion, withdrawal and task changes remain effective.

Context guidance distinguishes historical evidence from applicable user preferences and work agreements. Current agreements should inform the plan and remaining steps after tool completion, within their conditions and authorization. This does not introduce an autonomous background executor or turn all historical text into instructions.

Retains the 1.0.4 details page, manual check, silent automatic updates and strict save receipts. Bilingual guides, project records, version descriptions and download links are synchronized to 1.0.5.

Focused synthetic checks cover the original continuation regression, persisted recall through a real local Python worker, deletion, task changes and save receipts, alongside the existing release checks. Archive round-trip and publication scans pass. No private memory database, real recording or paid API was used. Actual model-driven note creation and installation into the user's live Host were not verified.

The existing startup and six-hour checks remain active, with installation handled by the Host manager. A manual check is available under Memory → Details. Mirrors may lag; the updater selects the newest valid available release. Save work and reload when the Host requires it, then confirm the running version.
