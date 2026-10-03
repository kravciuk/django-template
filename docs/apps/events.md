# apps.events

The `/events/` calendar: a month/week/day/list view of everything the owner has placed in time — document
deadlines, any note with calendar dates, and "quick notes" created straight from the calendar. Like
`apps.documents`, it is a **UI/API layer over `apps.content.Note`** — calendar placement lives on `Note` itself.
Its only models are the [Google Calendar sync](#google-calendar-sync-google) state (`events.0001_initial`,
`events.0002_googlecalendaraccount_oauth_client_id_and_more`).

## Data model (on `Note`, migration `content.0004_note_calendar_fields`)

| Field | Meaning |
|---|---|
| `starts_at` | Event start (`DateTimeField`, nullable, indexed). |
| `expires_at` | Inherited from `ExpiryModel` — the event **end** for notes, still the deadline for documents. |
| `all_day` | All-day event. Values are stored as **UTC midnight of each date**, and the end is the **inclusive** last day (so the full form shows the real last day). |
| `color` | `#rrggbb` override; empty = the per-source default from constance. |
| `recurrence` | RFC 5545 RRULE body, no `DTSTART` (e.g. `FREQ=YEARLY`, `FREQ=WEEKLY;INTERVAL=2;UNTIL=20271231T235959`). The series starts at `starts_at`, or `expires_at` if there's no start. |
| `remind_minutes_before` | Relative reminder offset (works for every occurrence of a recurring event). |
| `remind_at` | Inherited from `ExpiryModel` — now the **computed** next reminder fire time, never edited directly (see Reminders). |

A note's placement (`recurrence.event_bounds`): start = `starts_at or expires_at`; end = `expires_at` if there's a
start, else none (a single point in time).

`NoteKind.EVENT` is a **quick note**: created from the calendar modal, `body_format=PLAIN`,
`visibility=PRIVATE`, placed as a child of the owner's hidden **Events hub** — a `kind=NODE` root note marked
`json_data={"system_hub": "events"}` (`services.get_events_hub`, created on first use, recreated if trashed;
`Note.save()` forces NODE notes to UNLISTED). Quick notes are excluded from the home "Recent notes" feed
(`HomeView`); they still appear under the hub's detail page and in drafts.

## Wire conventions (`serializers.py`, `services.py`)

The API uses the FullCalendar/Google conventions: all-day `starts_at`/`ends_at` are plain dates and `ends_at` is
**exclusive**; timed values are ISO datetimes (naive ones are read in the active, i.e. the user's, time zone).
`services.to_api_end`/`from_api_end` are the only place the ±1 day all-day conversion happens. The modal shows
all-day ends inclusively and converts on save (`calendar.js`).

## Colors

Defaults live in constance (`/admin/constance/config/`, "Events" fieldset), not in code, so they're changeable
without a deploy:

- `EVENTS_NOTE_COLOR` — `#3a3f44` (dark gray)
- `EVENTS_DOCUMENT_COLOR` — `#5c3d2e` (dark brown)

Both use a custom `"color"` constance field (`CONSTANCE_ADDITIONAL_FIELDS` — color picker + hex validator).
Resolution: `note.color`, else the source default. `services.readable_text_color` picks white/near-black text by
WCAG luminance so a light custom color stays readable.

## Recurrence (`recurrence.py`)

Rules are expanded with `dateutil.rrule` in the owner's **local wall-clock time** and only then made
timezone-aware — a weekly 09:00 event stays at 09:00 across DST. All-day series expand by date. Expansion is capped
at `MAX_OCCURRENCES = 1000` per call. An imported `UNTIL…Z` is read as local (`ignoretz=True`), not rejected.
`build_rrule`/`parse_simple` back the simple UI controls (frequency / every N / until); any other rule is kept and
shown as "Custom". Recurring occurrences are **not draggable** — editing applies to the whole series
(per-occurrence exceptions are not implemented, see [future/calendar-next-steps.md](../future/calendar-next-steps.md)).
Monthly rules on the 29th–31st follow RFC 5545 and skip months without that day.

## Reminders (`reminders.py`, `signals.py`, `tasks.py`)

- `reminder_offset`: `remind_minutes_before`; for documents left at "Default", `EVENTS_DOCUMENT_REMIND_DAYS`
  (constance, default 14, `0` = off).
- `next_reminder_at(note, after)`: first fire time strictly after `after` (next occurrence for recurring notes;
  all-day events anchor at the owner's local midnight). Drafts, trashed notes and nodes never have one.
- `post_save` on `Note` (`signals.py`) recomputes `remind_at` via a queryset `update()` — no recursion, and
  `apps.content` stays unaware of reminders. A 15-minute grace window (`REMINDER_GRACE`) keeps a just-due reminder
  alive across a save; `json_data["reminded_at"]` remembers the last delivery so a save can't re-schedule it.
- `send_due_reminders` (beat, every 5 min): for each alive, non-draft note with `remind_at <= now`, re-checks the
  reminder still matches current settings (`is_still_due`), sends an in-app notification through
  `apps.notifications.services.notify(kind=SYSTEM, payload={title, body, url}, target=note)` with the time
  formatted in the owner's zone, then schedules the next one — never into the past, so a long beat outage doesn't
  replay every missed occurrence. `notifications.js` turns `payload.url` into a link.
- `manage.py refresh_event_reminders` recomputes `remind_at` for every alive note — run it **once after
  deploying** (existing documents have no `remind_at` yet) and after changing `EVENTS_DOCUMENT_REMIND_DAYS`.

Dev has no Celery worker/beat, so reminders don't fire in dev unless you call the task yourself:
`make docker-console app="shell -c 'from apps.events.tasks import send_due_reminders; send_due_reminders()'"`.

## Time zones

`User.timezone` (IANA name, blank = `settings.TIME_ZONE`, UTC) is edited on the profile page and activated per
request by `apps.users.middleware.UserTimezoneMiddleware` — see [users.md](users.md). The calendar runs
FullCalendar in that same named zone (Luxon plugin), so the calendar, the full note form (`datetime-local`) and
reminder texts all show the same wall-clock time while the DB stores UTC. Without a profile zone the calendar
shows UTC and offers a hint linking to the profile when the browser's zone differs.

Date/time *formats* follow the profile too (`User.date_format`/`time_format`, see
[users.md](users.md)): `calendar.js` sets FullCalendar's `eventTimeFormat`/`slotLabelFormat` (12/24-hour), the
week/day views' column headers ("Mon 05.10") and the list view's side date from `window.DisplayFormats`, and the
modal's start/end/until inputs are flatpickr pickers in the same format. The modal is created with
`bootstrap.Modal(el, { focus: false })` — flatpickr's popup lives outside the modal, and Bootstrap's focus trap
would otherwise pull focus out of its hour/minute inputs.

## URLs (`app_name = "events"`, under `i18n_patterns`)

| URL | View | Notes |
|---|---|---|
| `events/` | `CalendarView` | `LoginRequiredMixin`, `templates/events/calendar.html` |
| `events/api/feed/?start=&end=[&sources=note,document][&tags=a,b]` | `CalendarFeedView` | FullCalendar event source; 400 on a bad range |
| `events/api/tags/` | `CalendarTagsView` | Tag names used on the owner's calendar-placed notes (filter options) |
| `events/google/` (+ `oauth-client/`, `connect/`, `disconnect/`, `sync/`) | `google/views.py` | Google Calendar settings page and its POST actions; the OAuth callback is `oauth/google/callback/` in `core/urls.py`, outside `i18n_patterns` |
| `webhooks/google/calendar/` (POST, in `core/urls.py`, outside `i18n_patterns`) | `google/webhook.py` | Google push notifications; CSRF-exempt, public — see the sync section |
| `events/api/notes/` (POST), `events/api/notes/<public_id>/` (GET/PATCH/DELETE) | `QuickNoteViewSet` | Owner's alive notes only; documents and nodes 404 (edited on their own pages). Create = EVENT under the hub; `is_draft: true` on create backs "Open full form"; DELETE soft-deletes; rich-text bodies are never overwritten by the modal |

The feed returns `calendar_entries()` dicts (also used by the home widget): notes (recurring ones expanded) and
documents (all-day on `expires_at`, `editable: false`, link to `documents:detail`), excluding drafts, trash, nodes
and other owners' rows. The DB query is widened by a day on each side for all-day values.

## Frontend (`static/events/js/calendar.js`, `templates/events/`)

FullCalendar **6.1.21** (global bundle + all locales + `@fullcalendar/luxon3`) and Luxon 3, CDN-loaded from
jsdelivr like Bootstrap/HTMX. v7 exists, but its Luxon plugin was still a release candidate at the time.

- Desktop: month view; toolbar prev/next/today/"+ Event" and month/week/day/list. Click a day or drag across days
  to create, click an entry to edit (documents navigate to their page), drag/resize to reschedule (PATCH).
- Mobile (< 768 px): list view by default, view `<select>`, floating "+" button, tap a day to create
  (`dateClick`, touch only), long-press + drag (300 ms) for a range, swipe left/right for prev/next. Day-number
  nav links are disabled on phones — the browser's touch adjustment otherwise snaps a tap in a small cell onto the
  link. Crossing 768 px (rotation) switches list ↔ grid. Full-screen scrollable modal, 16 px inputs (no iOS
  zoom), 44 px tap targets, filters collapsed behind a button.
- Filters (Notes / Documents / tags) persist in `localStorage` (wrapped in try/catch).
- "Open full form" saves a draft quick note and redirects to `content:note_edit`; the full form's Save
  publishes it. `NoteForm` exposes the same calendar fields (dates, all-day, repeat, reminder, color);
  `DocumentForm` adds only the reminder select.
- Home page: `{% upcoming_events %}` (`templatetags/events_tags.py`) — next 7 days, max 10 — is a template tag so
  `apps.content` doesn't import `apps.events` for its view.
- `templates/events/_note_schedule.html` shows the placement on a note's detail page.

## Google Calendar sync (`google/`)

Sync of one Google calendar per user (picked on `events/google/`, default the primary one). Setup
(Google Cloud project, env vars): [operations/google-calendar.md](../operations/google-calendar.md). Every user
configures it for themselves on `events/google/`:

- **OAuth application.** A user connects through their own Google Cloud OAuth client (`GoogleOAuthClient`:
  client id + encrypted secret, entered on the settings page) if they set one, otherwise through the site-wide
  one (`GOOGLE_OAUTH_CLIENT_ID`/`SECRET`, optional). The page is available to every signed-in user; with
  neither client, "Connect" is disabled and the page explains how to create one (showing the exact redirect URI
  to register). Tokens refresh only through the client they were issued to, so the account stores
  `oauth_client_id` (`""` = the site client, for connections made before it existed); replacing that client
  revokes the grant and sets the account to `needs_reconnect`. Adding an own client while connected through the
  site's one keeps the connection until the user reconnects.
- **Direction** (`GoogleCalendarAccount.sync_direction`): *both ways* (default), *only from Google* (no writes to
  Google at all; on a conflict Google wins), *only to Google* (Google is a read-only copy: events created there
  aren't imported, and every linked event is treated like a document — changes and deletions in Google are put
  back, including events imported earlier while syncing both ways). Changing it runs a full resync.
- Calendar, "Sync enabled", "Include document expiry dates" (only matters when sending to Google).

**What syncs.** Ours → Google: every note the calendar shows (`services.syncable_notes`: alive, not a draft,
not a hub node, has a date) plus document expiry dates (all-day, `transparency: transparent`, read-only — edits
or deletion in Google are put back; toggle per account with "Include document expiry dates"). Google → ours:
new events in the selected calendar become quick notes (`kind=EVENT`, PLAIN, PRIVATE, under the Events hub);
edits and deletions of linked events apply to their notes (deletion = trash). Only events ending within
`GOOGLE_CALENDAR_IMPORT_PAST_DAYS` (constance, default 30) or recurring ones are created on either side on a full
sync; existing links are kept regardless.

**Pieces.**

| Module | Role |
|---|---|
| `models.py` | `GoogleOAuthClient` (OneToOne user: own client id + encrypted secret; survives a disconnect), `GoogleCalendarAccount` (OneToOne user: encrypted tokens, `oauth_client_id`, chosen calendar, `sync_direction`, `sync_token`, status/backoff) and `GoogleEventLink` (note ↔ event id, `origin` local/google, `state` active/detached, `snapshot`, `etag`, `note_synced_at`). Links live outside `Note.json_data` because every full `Note.save()` rewrites `json_data`, and a link must outlive a purged note (`note` is `SET_NULL`). |
| `google/crypto.py` | Fernet (`MultiFernet`) over `GOOGLE_TOKEN_ENCRYPTION_KEY` (comma-separated for rotation), fallback key derived from `SECRET_KEY`. Encrypts tokens and users' client secrets. |
| `google/credentials.py` | Which OAuth client to use: `for_user` (own, else site-wide) for a new connection, `for_account` (by `oauth_client_id`) for refreshing tokens, `by_id` for the callback. |
| `google/client.py` | Plain `requests` (no Google client libraries): OAuth (PKCE, offline access, refresh, revoke) + `calendarList.list(minAccessRole=owner)` and `events.list/get/insert/patch/delete`. Also `events.watch` / `channels.stop` for push channels. Maps HTTP errors to `GoogleAuthError`/`GoogleRateLimited`/`QuotaPaused`/`GoogleServerError`/`SyncTokenExpired`/`NotFound`/`Conflict`/`BadRequest`; every request first takes a slot from the shared budget (`ratelimit.py`). Scopes: `calendar.calendarlist.readonly` + `calendar.events.owned` (the latter also allows `events.watch`). |
| `google/ratelimit.py` | Shared request budget per OAuth client (= per Google Cloud project, which is what Google's quota counts): a per-minute counter in Redis capped by `GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE` (8000, below Google's 10,000), plus a pause of the whole client when Google reports a project-level limit (`userRateLimitExceeded` 60 s, `dailyLimitExceeded` 1 h). |
| `google/watch.py` | Push channels: `ensure_watch` (open / renew a day before expiry / move to a switched calendar / stop when push is off; TTL random 5–7 days so channels don't expire together), `stop_watch`. |
| `google/webhook.py` | `POST /webhooks/google/calendar/` — the receiver of Google's notifications (see below). |
| `google/mapping.py` | Note ↔ event conversion and the **projection**: a normalized dict (`summary`, `description`, `when`, `recurrence`, `reminder`, `color_id`) both sides are reduced to, so equal content compares equal. |
| `google/sync.py` | `sync_account` (lock → pull → push only if something to push → `ensure_watch` → schedule next run), `push_notes` (partial push), `switch_calendar`, `delete_created_events`, error bookkeeping. |
| `google/views.py` | Settings page, own OAuth client save/remove (POST), connect (POST), callback, disconnect (POST, optional "delete created events"; keeps the own client), "Sync now". |

**Change detection — a 3-way merge per projection key.** `link.snapshot` is the projection both sides agreed on
at the last sync. Pull: a key where Google ≠ snapshot changed in Google; if the note also differs from the
snapshot, the later edit wins (`event.updated` vs `note.updated_at`). Push: keys where the note ≠ snapshot are
sent as a PATCH of just those fields, so fields we don't map (location, attendees, EXDATE lines, conferencing)
are never overwritten. After a pull the snapshot becomes Google's projection; whatever still differs locally
(a newer local edit, a document, a rich-text body) goes out in the push that follows. Dirty notes are found by
`note.updated_at > link.note_synced_at` (or `note_synced_at` NULL); the nightly reconcile diffs every link.

**Echo prevention.** Pull writes run inside `sync.suppress_push()`, so `signals.queue_google_push` doesn't queue
them back; a pull only saves a note when a value actually changed; our own writes come back with the stored
`etag` and are skipped. Inserts use the event id `note.public_id.hex` and carry
`extendedProperties.private.note`: a retried insert gets 409 and adopts (or revives a cancelled) event instead
of duplicating, and a lost link is re-found by that property.

**Mapping notes.** All-day ↔ `start.date`/exclusive `end.date`; timed ↔ `dateTime` + the owner's
`User.timezone`. Recurrence: the single `RRULE:` line, our naive-local `UNTIL` ↔ Google's UTC `…Z` (a date for
all-day); `EXDATE`/`RDATE` aren't imported but stay in Google unless our rule changes. Reminder: one popup
override ↔ `remind_minutes_before`; none ↔ `useDefault` (so Google applies the calendar's default reminders).
Color: nearest of Google's 11 event colors (`GOOGLE_EVENT_COLORS`); empty ↔ no `colorId`. Body: PLAIN as is,
Markdown source, HTML via `libs.html.html_to_text`; Google's description is applied only to PLAIN notes.
Invitations (`organizer.self` false) are pull-only.

**When it runs.** Built for ~10,000 accounts:

- **Push notifications** (`GOOGLE_CALENDAR_PUSH_ENABLED`, needs a public https `SITE_URL`): every successful
  sync makes sure the account has a live `events.watch` channel. Google POSTs to `/webhooks/google/calendar/`
  on any change of the calendar; the webhook (CSRF-exempt, the only public endpoint) checks channel id, token
  and resource id, debounces per account (10 s) and queues the usual incremental sync on the `google` queue.
  A notification carries no data — the sync still lists the changes with the sync token.
- **Polling fallback**: each account has its own `next_sync_at` — `GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES` (10)
  without a live channel, `GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES` (60) with one, both ±25 % jitter —
  and `next_reconcile_at` (about daily, ±25 %). Beat `sync_google_calendars` every minute is the one
  dispatcher: due accounts oldest first, at most `GOOGLE_CALENDAR_DISPATCH_BATCH` (2000), not re-queued while
  still queued (`gcal:queued:<pk>`, 15 min), on the `google_bulk` queue. No nightly all-accounts reconcile.
- **Local changes**: saving, trashing or restoring a note sets `account.push_pending` and queues
  `push_notes_to_google` 30 s later (`signals.py`; trash/restore come from
  `apps.content.signals.notes_trashed/notes_restored`, since those use `.update()`); purging sets
  `push_pending` too. A sync runs its push phase only with `push_pending`, when the pull left something to send
  back, or on a reconcile/full sync — an idle run is one `events.list` call and ~5 queries, whatever the
  number of notes (links are loaded per page, not per event).
- Writes per run are capped by `GOOGLE_CALENDAR_MAX_WRITES_PER_RUN`; requests per OAuth client per minute by
  `GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE` — a used-up budget postpones the account (`QuotaPaused`: no
  backoff, no error recorded, `next_sync_at` = when the budget is back). `GOOGLE_CALENDAR_SYNC_ENABLED`
  (constance) is the master switch.
- In dev (no worker, no https) push is inactive, "Sync now" runs inline and per-save pushes aren't queued
  (`GOOGLE_CALENDAR_SYNC_INLINE`/`GOOGLE_CALENDAR_ENQUEUE_ON_SAVE`); `manage.py google_calendar_sync [--user]
  [--full]` runs a sync by hand.

**Errors.** Revoked/expired grant (`invalid_grant`, repeated 401), the OAuth client the tokens were issued to no
longer configured, or stored tokens that can't be decrypted any more → status `needs_reconnect`, tokens cleared,
one in-app notification (the push channel is forgotten — it can't be stopped without tokens and expires on its
own). Calendar gone (404) → status `error` + notification. Per-user/calendar rate limits (`rateLimitExceeded`,
`quotaExceeded`), 5xx, network → exponential backoff of that account in `retry_after` (max 60 min). Project-level
limits pause every account on that OAuth client instead (`QuotaPaused`, see `ratelimit.py`). A problem with one
event is recorded on its link and the run continues. A channel Google refuses leaves the account on polling.

**Switching calendars** removes the events this site created from the old calendar (they're re-created in the
new one) and marks notes imported from it `detached` (kept here, no longer synced). **Disconnecting** revokes
the grant and deletes the account and links (the user's own OAuth client is kept); imported notes stay as normal notes, and events created here stay
in Google unless "Also delete the events this site created" is ticked.

**Limitations.** Single-occurrence exceptions (`recurringEventId`) and EXDATE/RDATE aren't represented here;
one reminder per note; colors snap to Google's palette; location/attendees/attachments aren't imported;
without push (dev, http, switch off) changes arrive up to the sync interval late; last writer wins per field by
clock; admin bulk trash/restore (bypasses the signals) only syncs on the account's daily reconcile; losing `GOOGLE_TOKEN_ENCRYPTION_KEY`
means everyone reconnects and re-enters their own client secret; notification texts are in the default language.

## Known gaps

See [future/calendar-next-steps.md](../future/calendar-next-steps.md): ICS subscription feed, push webhooks for
Google sync, single-occurrence exceptions, view/date in the URL. Notification texts are built in the default language
(the Celery worker has no per-user language).
