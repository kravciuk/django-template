# apps.events

The `/events/` calendar: a month/week/day/list view of everything the owner has placed in time — document
deadlines, any note with calendar dates, and "quick notes" created straight from the calendar. Like
`apps.documents`, it is a **UI/API layer over `apps.content.Note` with no models and no migrations** — calendar
placement lives on `Note` itself.

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

## Known gaps

See [future/calendar-next-steps.md](../future/calendar-next-steps.md): ICS subscription feed, Google Calendar
sync, single-occurrence exceptions, view/date in the URL. Notification texts are built in the default language
(the Celery worker has no per-user language).
