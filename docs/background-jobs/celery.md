# Celery

## Queues (`core/celery.py`)

Four queues: `high`, `low` (default), and two for the Google Calendar sync. Routing (`task_routes`):

- anything named `*.high_priority_task` → `high` (no task uses that suffix yet — infrastructure for later);
- `apps.events.tasks.sync_google_calendar*` and `reconcile_google_calendars` → `google_bulk` (the per-minute
  dispatcher and scheduled background syncs);
- `apps.events.tasks.push_notes_to_google` → `google`; syncs someone waits on (push notification, "Sync now",
  admin actions) are sent to `google` explicitly via `apps.events.tasks.queue_account_sync(..., interactive=True)`;
- everything else → `low`.

The Google queues exist so that thousands of routine syncs never delay reminders/cleanup on `low`, and a backlog
of background syncs never delays one a user is waiting for.

In prod each queue has its own worker container (`celery-high`, `celery-low`, `celery-google`,
`celery-google-bulk`; the Google ones with `-O fair --prefetch-multiplier=1` and configurable concurrency) — see
[architecture/docker-topology.md](../architecture/docker-topology.md). **Dev runs no Celery worker or beat
process at all** — tasks are importable and callable synchronously in a shell, but nothing consumes the queue
unless you start a worker manually.

## Beat schedule (`core/celery.py::app.conf.beat_schedule`)

| Task | Schedule | What it does |
|---|---|---|
| `core.tasks.update_geoip_database` | daily 03:00 | Runs `scripts/init_geoip.sh` — downloads MaxMind GeoLite2-City if `MAXMIND_LICENSE_KEY` is set to a real key; no-ops otherwise. |
| `apps.content.tasks.cleanup_stale_drafts` | daily 02:00 | Soft-deletes (trashes) `Note` drafts untouched for `DRAFT_RETENTION_DAYS` (default 7). See [apps/content.md](../apps/content.md#taskspy--cleanup_stale_drafts). |
| `apps.notifications.tasks.cleanup_old_notifications` | daily 04:00 | Hard-deletes **read** notifications older than `NOTIFICATIONS_RETENTION_DAYS` (default 90), by `created_at`. See [apps/notifications.md](../apps/notifications.md#retention-taskspy). |
| `apps.events.tasks.send_due_reminders` | every 5 min | Sends an in-app notification for every calendar note/document whose computed `remind_at` has come, then schedules its next one. See [apps/events.md](../apps/events.md#reminders-reminderspy-signalspy-taskspy). Run `manage.py refresh_event_reminders` once after deploying it. |
| `apps.events.tasks.sync_google_calendars` | every minute | The one dispatcher of background Google Calendar syncs: queues (on `google_bulk`) accounts whose own jittered `next_sync_at` — or daily `next_reconcile_at` (then with `reconcile=True`) — has come, oldest first, at most `GOOGLE_CALENDAR_DISPATCH_BATCH` (constance) per run, skipping ones backing off or still queued. See [apps/events.md](../apps/events.md#google-calendar-sync-google). |
| `apps.links.tasks.refetch_missing_favicons` | daily 05:00 | Retries `fetch_favicon` for every `Link` still without a favicon. See [apps/links.md](../apps/links.md#favicon-fetching-servicespy-utilspy--ssrf-relevant). |

`apps.events.tasks.reconcile_google_calendars` used to run for every account at once daily at 03:30 — the kind of
synchronized burst Google advises against; every account is now reconciled about daily at its own time by the
dispatcher above, and the task only remains as a manual "make every account due for a reconcile now".

There used to be another entry, `core.tasks.backup_database` (daily 00:00, driving
`scripts/backup_db.sh`/`restore_db.sh`) — **removed**, along with both scripts: `pg_dump` run from the django
image was a major version behind the `postgres` service's own image and silently produced empty backup files
every time. There is currently **no automated backup** — manual backup/restore is
`make docker-db-backup`/`docker-db-restore` (`pg_dump -Fc`/`pg_restore` run inside the `postgres` container
itself), see [operations/running-the-project.md](../operations/running-the-project.md).

**`apps.common.management.commands.purge_trash` is not on this schedule** — it auto-discovers every
`SoftDeleteModel` subclass and hard-deletes anything trashed past `TRASH_RETENTION_DAYS`, but today it must be run
manually or wired into an external cron — nothing inside the Django/Celery process calls it automatically. This
means a `Note`/`Attachment`/`Comment` soft-deleted via `cleanup_stale_drafts` or a user action will sit in the
trash **forever** unless someone runs `purge_trash` themselves. See
[known-issues.md](../known-issues.md) and consider fixing this via
[future/feature-gaps.md](../future/feature-gaps.md).

## `core/tasks.py` — shared shell-out helper

`update_geoip_database` goes through a small helper, `_run_script(script_name, *args)`, which runs
`/bin/bash /scripts/<script_name>` via `subprocess.run(check=False)`, logs stdout/stderr, and manually raises
`RuntimeError` on a non-zero exit code — so a failed GeoIP update surfaces as a visible Celery task failure, not a
silent no-op. `/scripts/` is where `scripts/` gets copied/mounted inside the container (see
[architecture/docker-topology.md](../architecture/docker-topology.md)). This helper used to also run
`scripts/backup_db.sh` for `backup_database` — that task and both `scripts/backup_*.sh` files were removed (see
the Beat schedule section above).

## App-local tasks

- `apps/content/tasks.py::cleanup_stale_drafts` — see [apps/content.md](../apps/content.md).
- `apps/notifications/tasks.py::cleanup_old_notifications` — see [apps/notifications.md](../apps/notifications.md).
- `apps/links/tasks.py::refetch_missing_favicons` — see [apps/links.md](../apps/links.md).

Both are named explicitly (`name="..."`) matching the beat schedule's task-name strings — if you rename either
function, the beat schedule entry must be updated to match, or the schedule will silently reference a task that
no longer resolves.
