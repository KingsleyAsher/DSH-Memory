# DSH Memory 1.0.13

During a knowledge service handoff or reconnect, the Memory page keeps local entries visible and shows a reconnecting status. It reloads linked memories on readiness and retries after about three seconds if the notification is missed.

Reopening the same session can display the last successful snapshot while refreshing in the background. Connection or permission changes invalidate the old snapshot immediately.

Pair with Knowledge Base plugin 2.5.6. Release checks cover readiness, fallback retry, reopen after expiry, and invalidation. Fully exit DSH including the tray process and reopen after installing.
