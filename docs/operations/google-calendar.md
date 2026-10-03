# Google Calendar sync — deployment, configuration, scaling

Runbook for operating the Google Calendar sync (`apps.events.google`) in prod. How the sync itself works (merge,
mapping, directions): [apps/events.md](../apps/events.md#google-calendar-sync-google).

1. [What runs where](#1-what-runs-where)
2. [Google Cloud setup](#2-google-cloud-setup)
3. [Configuration reference](#3-configuration-reference)
4. [Deploy](#4-deploy)
5. [Push notifications](#5-push-notifications)
6. [Scaling](#6-scaling)
7. [Monitoring](#7-monitoring)
8. [Troubleshooting](#8-troubleshooting)
9. [Turning it off, rolling back](#9-turning-it-off-rolling-back)
10. [For users: connecting a calendar](#10-for-users-connecting-a-calendar)

## 1. What runs where

| Piece | Where | Role |
|---|---|---|
| Settings page, OAuth connect/callback | `django` (`/events/google/`, `/oauth/google/callback/`) | Each user connects their own Google account, picks a calendar, direction, optionally their own OAuth application. |
| Webhook | `django` (`POST /webhooks/google/calendar/`) | Google's push notifications ("this calendar changed") → queues a sync. Public, CSRF-exempt. |
| Dispatcher | `celery-beat` → `sync_google_calendars` every minute, on `google_bulk` | Queues accounts whose own `next_sync_at` / `next_reconcile_at` has come (polling fallback + daily reconcile). |
| Workers | `celery-google` (queue `google`), `celery-google-bulk` (queue `google_bulk`) | `google`: syncs someone waits on (notification, "Sync now", a just-saved note). `google_bulk`: scheduled syncs. |
| Redis (cache, DB 1) | `gcal:sync:<pk>`, `gcal:queued:<pk>`, `gcal:webhook:<pk>`, `gcal:quota:<client>:<minute>`, `gcal:paused:<client>` | Per-account lock, dispatch dedup, webhook debounce, shared request budget per OAuth client. |
| Postgres | `events_googleoauthclient`, `events_googlecalendaraccount`, `events_googleeventlink` | Users' own OAuth clients, connections (tokens, schedule, push channel), note ↔ event links. |

Every user configures the sync for themselves; the site admin only provides the infrastructure and, optionally, a
site-wide OAuth application.

## 2. Google Cloud setup

### 2.1 Site-wide OAuth application (optional, done by the admin)

Used by every user who didn't enter their own. Without it, users must bring their own (2.2).

1. In [Google Cloud Console](https://console.cloud.google.com/) create (or pick) a project and enable the
   **Google Calendar API** (APIs & Services → Library).
2. **OAuth consent screen** (Google Auth Platform → Branding / Audience / Data access):
   - user type **External** (or Internal for a Google Workspace domain);
   - scopes `https://www.googleapis.com/auth/calendar.calendarlist.readonly` and
     `https://www.googleapis.com/auth/calendar.events.owned` (the latter also covers push notifications);
   - **publishing status "In production".** In "Testing" Google issues refresh tokens that expire after
     **7 days** — the sync silently stops every week.
3. **Credentials → Create credentials → OAuth client ID**, type **Web application**, authorized redirect URI —
   exactly, trailing slash included:
   - prod: `https://<your-domain>/oauth/google/callback/`
   - dev: `http://localhost:81/oauth/google/callback/` (Google allows plain http only for `localhost`)
4. Put the client ID and secret into `.env.prod` (section 3.1).

### 2.2 Users' own OAuth applications

A user can create the same thing in their own Google Cloud project (steps 1–3 above, with this site's redirect
URI) and enter the client ID and secret on `/events/google/` → "Use my own application". The page shows the
steps, the scopes and the exact redirect URI. The secret is stored encrypted and never shown back. An own
application has its **own Google quota**, separate from the site-wide one.

### 2.3 Google verification (before more than 100 users)

Calendar scopes are *sensitive*. An unverified application works for at most **100 users** and shows an
"unverified app" warning on the consent screen. Before opening the site-wide application to more users, submit it
for Google's verification: homepage and privacy policy on a verified domain (the policy must describe how Google
user data is used and stored), the authorized domains verified, and a demo video of the OAuth flow. Expect weeks.

## 3. Configuration reference

### 3.1 Environment (`.env.prod`; dev: `.env`)

| Variable | Default | Notes |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | `""` | Site-wide OAuth application (2.1). Empty = users must bring their own. **Changing the client ID** sends everyone connected through the old one to "Needs reconnecting" — tokens refresh only through the client they were issued to. |
| `GOOGLE_OAUTH_REDIRECT_URI` | `""` (built from the request) | **Required in prod**: `https://<your-domain>/oauth/google/callback/`. Behind the outer TLS proxy Django sees `http` (the inner nginx forwards `X-Forwarded-Proto $scheme`) and would build a URI Google rejects. One URI for every client, the site's and users' own. |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | `""` (derived from `SECRET_KEY`) | Fernet key(s) encrypting stored tokens **and** users' client secrets — see 3.4. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |
| `SITE_URL` | `""` | Public base URL, e.g. `https://<your-domain>`. Links from Google events back to notes, and the base of the push webhook address — push only works with `https://`. |
| `ALLOWED_HOSTS` | — | Must include the domain (Google's notifications arrive with that `Host`). |
| `CELERY_GOOGLE_CONCURRENCY` | `8` | Processes of `celery-google`. |
| `CELERY_GOOGLE_BULK_CONCURRENCY` | `16` | Processes of `celery-google-bulk`. |
| `GOOGLE_CALENDAR_SYNC_INLINE` | `False` (dev: `True`) | Run "Sync now" in the request instead of queueing it (dev has no worker). |
| `GOOGLE_CALENDAR_ENQUEUE_ON_SAVE` | `True` (dev: `False`) | Queue an immediate push after each note save/trash/restore. |

### 3.2 Runtime settings (`/admin/constance/config/` → "Google Calendar")

| Key | Default | Meaning / when to change |
|---|---|---|
| `GOOGLE_CALENDAR_SYNC_ENABLED` | on | Master switch: off = no background syncs, no pushes, notifications ignored. Connections are kept. |
| `GOOGLE_CALENDAR_PUSH_ENABLED` | off | Push notifications (section 5). Needs an https `SITE_URL`. |
| `GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES` | 10 | Polling interval of accounts **without** a live push channel (±25 % jitter). |
| `GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES` | 60 | Fallback polling of accounts **with** a live channel. Raise to save quota (section 6). |
| `GOOGLE_CALENDAR_IMPORT_PAST_DAYS` | 30 | How far back one-off events are imported/sent on a full sync. |
| `GOOGLE_CALENDAR_MAX_WRITES_PER_RUN` | 200 | Google writes per account per run; the rest waits for the next run. |
| `GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE` | 8000 | Shared request budget **per OAuth client** (Google's limit: 10,000/min per project). Raise only after Google raised the project quota. |
| `GOOGLE_CALENDAR_DISPATCH_BATCH` | 2000 | Max accounts the dispatcher queues per minute. Must stay above *accounts ÷ polling interval* (section 6). |

### 3.3 Worker and database capacity

- Workers are prefork with high concurrency (the tasks mostly wait on Google), `-O fair --prefetch-multiplier=1`
  so one long sync doesn't hold queued ones back. They don't run migrations on startup (`RUN_MIGRATIONS=false`).
- `CONN_MAX_AGE=0` and PgBouncer in transaction mode: a connection is held only while a task/request runs. Keep
  **gunicorn workers + `django-ws` workers + the concurrency of every Celery worker** under
  `PGBOUNCER_MAX_CLIENT_CONN` (100). Default on 4 CPUs: 9 + 2 + 4 + 4 + 8 + 16 = 43.

### 3.4 Encryption key: keep, rotate

`GOOGLE_TOKEN_ENCRYPTION_KEY` must be kept safe and stable — losing it means every user reconnects (and re-enters
their own secret). Without it the key is derived from `SECRET_KEY`, so rotating `SECRET_KEY` would have the same
effect: set a dedicated key in prod.

To rotate: prepend a new key (`new,old`) and deploy — the first key encrypts, all decrypt. **Don't drop the old
key while anything is still encrypted with it:** access tokens are re-encrypted on every refresh, but refresh
tokens only when Google hands out a new one (it usually doesn't), and client secrets only when the user saves them
again. Whatever can't be decrypted after the old key is gone puts that account into "Needs reconnecting"; the sync
itself keeps working for everyone else.

## 4. Deploy

### 4.1 Prerequisites

- [ ] Public **https** domain with a certificate Google accepts (no self-signed) — required for push.
- [ ] The outer TLS proxy passes `/oauth/google/callback/` and `/webhooks/google/calendar/` to the site's nginx
      unchanged (no auth wall, no IP filter, POST allowed).
- [ ] `.env.prod`: `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, `SITE_URL`, `ALLOWED_HOSTS`; the
      site-wide client if one is used (section 3.1).
- [ ] For more than 100 users through the site-wide application: Google verification done (2.3).

### 4.2 Deploy / upgrade

```bash
make docker-prod-db-backup        # pg_dump inside the postgres container -> backups/
make docker-prod-build            # django image first, then the rest
make docker-prod-up               # the django container applies migrations on startup
make docker-prod-console app="showmigrations events"   # expect [X] 0001, 0002, 0003
make docker-prod-ps               # celery-google and celery-google-bulk are Up
```

Migrations of the sync, all additive:
`0001` connections and links; `0002` users' own OAuth clients, sync direction; `0003` push channel fields and the
per-account schedule — its data step spreads existing accounts' next sync over 10 minutes and next reconcile over
a day, so they don't all become due at once after the deploy.

### 4.3 Verify

1. `/events/google/` opens; Connect → Google consent → back on the page with a calendar selected.
2. Within a minute the account has a "Last synced" time; `make docker-logs-celery` shows no
   "Google Calendar sync failed".
3. Create a note with a date → it appears in Google within ~30 s (immediate push).
4. Enable push (section 5) and check that a change made in Google arrives within seconds.

## 5. Push notifications

With push on, Google notifies the site of every change in a connected calendar (`events.watch`) and the change is
synced within seconds; polling drops to a rare fallback (`…_WATCHED_SYNC_INTERVAL_MINUTES`). No new Google
permissions or domain verification are needed, also for users' own applications.

1. Prerequisites from 4.1 (https, the proxy passes `/webhooks/google/calendar/`).
2. Turn on `GOOGLE_CALENDAR_PUSH_ENABLED` in constance.
3. Each account opens its channel on its next sync (within ~10 min, or "Sync now"). Check:
   - `/admin/events/googlecalendaraccount/?push=live` lists the accounts;
   - the access log shows a `POST /webhooks/google/calendar/` right after each channel opens (Google's `sync`
     handshake, answered 204);
   - the settings page says "Changes from Google: arrive within seconds".
4. Edit an event in Google — the note changes within seconds.

Channels live 5–7 days (random, so channels opened together don't expire together) and the sync renews them a day
before expiry. Turning the switch off stops each channel at the account's next sync; turning the master switch off
makes the webhook ignore notifications. A channel Google refuses leaves that account on plain polling (log line
"Google Calendar push channel couldn't be opened"). In dev (http) push is never active.

## 6. Scaling

### 6.1 Capacity model

Google's Calendar API quota is **per Google Cloud project, i.e. per OAuth client**: 10,000 requests/minute,
600/minute per user, 1,000,000/day before billing. Users with their own application don't count against the
site-wide one.

| Cost | Formula | 10,000 accounts |
|---|---|---|
| Polling, push off | accounts × 1440 ÷ `SYNC_INTERVAL` | 10 min → **1.44M/day — over the daily limit** |
| Polling fallback, push on | accounts × 1440 ÷ `WATCHED_SYNC_INTERVAL` | 60 min → 240k/day |
| Each change in Google | 1 `events.list` (notifications are debounced per account) | depends on activity |
| Each change here | 1 write per changed note (its echo comes back in the next list, no extra request) | depends on activity |
| Daily reconcile | 1 `events.list` + writes only for real differences | 10k/day |
| Token refresh | ≤ 1 per account per hour (OAuth endpoint, not the Calendar quota) | ≤ 240k/day |

Rules of thumb:

- **Without push**, one OAuth project carries about 1,000,000 ÷ (1440 ÷ 10) ≈ **6,900 accounts**. Above that,
  push is required (or a longer polling interval).
- **With push**, the fallback costs 24 calls/account/day; the rest depends on how active the calendars are.
  Keep total daily calls under ~70 % of 1M; if not, raise `WATCHED_SYNC_INTERVAL_MINUTES` (e.g. 120–240) or ask
  Google for a higher quota (Cloud Console → APIs & Services → Google Calendar API → Quotas).
- **Dispatch**: `DISPATCH_BATCH` must exceed accounts ÷ shortest polling interval per minute
  (10,000 ÷ 10 = 1,000 without push), otherwise the backlog grows.
- **Workers**: concurrency needed ≈ syncs per minute × average sync seconds ÷ 60. An idle sync takes well under
  a second (one Google call, ~5 queries, independent of the number of notes); first full syncs of big calendars
  take longer. 10,000 watched accounts ≈ 170 fallback syncs/min + notification syncs → the default 16 + 8 is
  ample; raise `CELERY_GOOGLE_BULK_CONCURRENCY` if the `google_bulk` queue keeps growing (section 7).
- **Database**: one `GoogleEventLink` per synced event and one `Note` per imported event — plan for
  accounts × events per calendar rows (10,000 × 500 = 5M). The dispatcher query and the webhook lookup are
  indexed (≈1 ms and ≈0.01 ms measured with 10,000 accounts).

### 6.2 What protects the quota automatically

- Shared request budget per OAuth client (`GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE`): when used up, syncs are
  postponed to when it's back (log "Google Calendar sync postponed") — not counted as errors, no backoff.
- A project-level limit reported by Google (`userRateLimitExceeded`) pauses every account on that client for
  60 s, the daily limit (`dailyLimitExceeded`) for an hour. Per-user/calendar limits (`rateLimitExceeded`,
  `quotaExceeded`) back off only that account (exponential, up to 60 min).
- Jittered schedule (±25 %), per-account daily reconcile instead of a nightly burst, randomized channel lifetimes,
  dispatch batch cap and dedup, per-account debounce of notifications.

### 6.3 Rolling out to many users

1. Google verification of the site-wide application (2.3) and the multi-user prerequisites — the project itself
   is still single-user today, see [future/multi-user-migration.md](../future/multi-user-migration.md).
2. Push on before the user count passes a few thousand.
3. Open connections in waves (e.g. 500–1,000 a day): every first connect runs a full sync (up to 200 writes per
   run, the rest follows in the next runs) — the heaviest moment for quota and workers.
4. Watch the signals in section 7 after each wave; tune concurrency / intervals before the next.

## 7. Monitoring

```bash
# Queue backlog (Celery broker = Redis DB 0, one list per queue). Should hover near 0.
docker compose -f docker-compose.prod.yml exec redis redis-cli -n 0 LLEN google_bulk
docker compose -f docker-compose.prod.yml exec redis redis-cli -n 0 LLEN google

# What the workers are doing right now
docker compose -f docker-compose.prod.yml exec celery-google-bulk celery -A core inspect active

# Sync log lines (failures, postponements, dispatcher summary, push channels)
make docker-logs-celery | grep -E "Google Calendar (sync failed|sync postponed|syncs queued|push channel)"
```

Accounts by state (`make docker-prod-shell`):

```python
from django.db.models import Count
from django.utils import timezone
from apps.events.models import GoogleCalendarAccount as A
A.objects.values("status").annotate(n=Count("pk"))                       # active / needs_reconnect / error
A.objects.filter(watch_expires_at__gt=timezone.now()).count()             # live push channels
A.objects.filter(status="active", sync_enabled=True, next_sync_at__lt=timezone.now()).count()  # overdue
```

| Signal | Healthy | Act when |
|---|---|---|
| `google_bulk` queue length | ~0, short spikes | grows minute after minute → raise `CELERY_GOOGLE_BULK_CONCURRENCY` (mind PgBouncer, 3.3) |
| Overdue accounts | a few | hundreds and rising → dispatch batch / workers / quota (postponements in the log) |
| "sync postponed" lines | rare | constant → quota-bound: push on, longer fallback interval, Google quota increase |
| `needs_reconnect` count | stable | jumps → key rotation, client ID change, Google revoked the application |
| Live push channels | ≈ connected accounts (push on) | far fewer → "push channel couldn't be opened" in the log, webhook reachability |

Admin: `/admin/events/googlecalendaraccount/` (status, direction, OAuth client, push channel and expiry, next sync /
reconcile, push pending, last error; filters by status, direction, push channel; "Sync now" / "Force a full
resync"), `/admin/events/googleoauthclient/` (users' own client IDs, never the secret),
`/admin/events/googleeventlink/` (which note mirrors which event).

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Google shows `redirect_uri_mismatch` on Connect | `GOOGLE_OAUTH_REDIRECT_URI` differs from the URI registered on the OAuth client (scheme, domain, trailing slash). |
| Sync stops for everyone after ~7 days | Consent screen in "Testing" — set it to "In production"; users reconnect. |
| Many accounts suddenly "Needs reconnecting" | Old encryption key dropped too early (3.4), site client ID changed, or Google revoked/suspended the application. |
| A user's account "Needs reconnecting" after editing "Google application" | Expected: the connection was made through the client they replaced — reconnect. |
| No live push channels | Switch off, `SITE_URL` not `https://`, or Google refuses (see the log line). |
| Channels exist but no `POST /webhooks/google/calendar/` arrives | Outer proxy blocks/rewrites the path, invalid certificate, `ALLOWED_HOSTS` missing the domain (Django answers 400). |
| Changes from Google arrive only after up to 60 min | Notifications don't reach the site (row above) — the fallback polling is doing the work. |
| "Google Calendar sync postponed" all the time | Request budget used up: enable push, raise the fallback interval, or get a higher Google quota and then raise `…_MAX_REQUESTS_PER_MINUTE`. |
| `google_bulk` queue keeps growing | Too few workers for the load, or a dispatch batch below accounts ÷ interval. |
| Local edits don't reach Google | Direction "Only from Google"; sync disabled; or the change bypassed signals (admin bulk action) — it goes out with the account's daily reconcile, or "Force a full resync" in the admin. |

Manual tools:

```bash
make docker-prod-console app="google_calendar_sync --user <username> --full"   # one account, in the foreground
make docker-prod-shell
# >>> from apps.events.tasks import reconcile_google_calendars; reconcile_google_calendars()
#     every account becomes due for a reconcile; the dispatcher works through them in batches
```

## 9. Turning it off, rolling back

- **Pause everything**: constance `GOOGLE_CALENDAR_SYNC_ENABLED` off — no background syncs or pushes,
  notifications ignored, connections and data kept. Back on: syncs resume on schedule.
- **Push only**: `GOOGLE_CALENDAR_PUSH_ENABLED` off — channels are stopped at each account's next sync; polling
  goes back to `SYNC_INTERVAL_MINUTES` (check the daily-quota math in 6.1 first).
- **Roll the code back** to a release before migration `0003`: the new columns are NOT NULL without a DB
  default, so old code creating accounts would fail. Reverse the migration first, **while the new code is still
  deployed**: `make docker-prod-console app="migrate events 0002"` (drops the push/schedule columns; open push
  channels simply expire), then deploy the old release. Same for `0002` → `migrate events 0001` (drops users'
  own OAuth clients and directions).

## 10. For users: connecting a calendar

Profile → "Google Calendar" card, or the "Google Calendar" button on `/events/` → optionally "Use my own
application" (client ID + secret) → **Connect** → Google consent (allow both permissions) → back on the settings
page the primary calendar is selected and a first full sync runs. Then:

- **Calendar** — switching removes the events this site created from the old calendar.
- **Sync direction** — *both ways* (default); *only from Google* (nothing is written to Google, Google wins
  conflicts); *only to Google* (Google is a read-only copy: events created in Google aren't imported, changes
  and deletions made there to the copied events are put back). Changing it runs a full resync.
- **Include document expiry dates**, **Sync enabled**, "Sync now", Disconnect (keeps the own application).

Replacing or removing the own application that the current connection was made through revokes it — reconnect
afterwards. Adding an own application while connected through the site's one keeps the connection until the
user reconnects.
