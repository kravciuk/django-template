# Known issues

Functional bugs, drift, and code smells found during this review — not security-specific (those are in
[security-considerations.md](security-considerations.md)). Each app's own doc under [`apps/`](apps/) links back
here instead of repeating the detail. Severity is informal (High/Medium/Low), judged by user-facing impact on
this single-user app today, not by exploitability.

## The single biggest gap relative to the project's stated purpose (RESOLVED)

**Resolved by `apps.events`:** document deadlines and calendar events now send in-app reminders
(`apps.events.tasks.send_due_reminders`, every 5 minutes; default lead `EVENTS_DOCUMENT_REMIND_DAYS`) — see
[apps/events.md](apps/events.md#reminders-reminderspy-signalspy-taskspy). Original finding, kept for history:

**There was no warranty/contract deadline *notification* mechanism**, despite `expires_at`/`remind_at` fields
existing on `Note` (and `Attachment`) via `apps.common.models.ExpiryModel`. Nothing — no Celery Beat task, no
in-app notification, no email — ever reads these fields to alert the owner that something is expiring. The only
place `expires_at` is used is a passive "expiring soon" list on the home page
(`apps.content.views.HomeView.get_context_data`), which only helps if the owner happens to visit the home page
before the deadline. Since "контроль сроков гарантии" (warranty deadline tracking) is one of the two things the
owner described this project as being *for*, this is the top candidate for follow-up work — see
[future/feature-gaps.md](future/feature-gaps.md) for a concrete proposal.

## KI-1: CLAUDE.md is out of date

*Severity: High (for AI-assisted development specifically)* — the root `CLAUDE.md` describes a generic
GeoDjango/geo-tracking template and says `apps/users` "currently exists only as an empty scaffold (no models, no
views — just a placeholder `urls.py`)." Neither is true anymore: `apps.users` has a real custom `User` model, a
customized admin, a login signal, and two working JWT endpoints (see [apps/users.md](apps/users.md)) — and
`CLAUDE.md` doesn't mention `apps.content`, `apps.documents`, `apps.attachments`, `apps.comments`,
`apps.sharing`, `apps.links`, or `apps.notifications` at all, i.e. essentially the entire real feature surface of
the project. Any AI agent or new contributor reading only `CLAUDE.md` would form a badly wrong picture of what
this codebase does. This documentation set is the practical mitigation; whether to also rewrite `CLAUDE.md`
itself is a decision left to the project owner (see [future/](future/)).

## KI-2: Note kind form choices test failure (RESOLVED)

**Resolved:** offering `NODE` (hidden hub) and, since `apps.events`, `EVENT` (calendar quick note) in `NoteForm`
is the deliberate product decision; the test is now
`test_note_form_kind_field_offers_only_the_kinds_it_can_present` and asserts `{NOTE, ALBUM, NODE, EVENT}`.
Original finding:

*Severity was: Medium — an actual currently-failing test.* `tests/unit/test_content_views.py::test_note_form_kind_field_only_offers_note_and_album`
asserts `NoteForm`'s `kind` field only offers `{NoteKind.NOTE, NoteKind.ALBUM}`. It currently fails:

```
assert {NoteKind.ALBUM, NoteKind.NODE, NoteKind.NOTE} == {NoteKind.ALBUM, NoteKind.NOTE}
```

`apps/content/forms.py`'s `FORM_NOTE_KIND_CHOICES` (lines 54–61) intentionally includes `NoteKind.NODE` alongside
`NOTE`/`ALBUM`, with a comment explaining it's "a hidden hub note... its visibility is forced to UNLISTED on save
regardless of what the form's `visibility` field ends up submitting." Either the test predates that addition and
is simply stale, or exposing "Node" as a user-selectable kind in the public create/edit form is itself the bug
(a `NODE` note is described everywhere else as an internal/hidden construct, not something a user should
knowingly create via the regular form). This needs a product decision, not just a test fix — see
[future/feature-gaps.md](future/feature-gaps.md).

## KI-3: health check returns 500 (RESOLVED)

*Severity was: Low today, Medium if `/health/` is ever wired into real infra.* `GET /health/` (django-health-check)
used to return HTTP 500 — its default checks include `Mail(alias='default')`, which attempted an SMTP connection
and got `Connection refused` since no `EMAIL_BACKEND`/`EMAIL_HOST` was configured anywhere, so Django fell back
to its own SMTP default (`localhost:25`), which nothing is listening on.

**Fixed** as a side effect of adding django-allauth (which needs a real `EMAIL_BACKEND` to send verification/
password-reset emails) — `core/settings/auth.py` now sets `EMAIL_BACKEND` from env, defaulting to
`django.core.mail.backends.console.EmailBackend` in dev. `/health/` returns 200 again.

## KI-4: treebeard 8 deprecation warnings

*Severity: Low (forward-compat only).* Running pytest surfaces `RemovedInTreebeard8Warning` twice:
`Note.get_ancestors()` (used in `templates/content/note_detail.html` for breadcrumbs) and
`Note.get_children()` (`apps/content/views.py:181`) — both instance methods deprecated in favor of the manager
equivalents (`Note.objects.get_ancestors(note)` / `get_children(note)`). Not a functional bug today, but will
break outright on a future treebeard major version.

## KI-5: missing i18n wrapping

*Severity: Low functionally, but a direct violation of the project's own stated convention* ("Always use string
localization: gettext_lazy for models, gettext for views and translate, blocktranslate in templates" —
`CLAUDE.md`). Coverage is inconsistent — some files/templates are fully compliant, most are not:

**Compliant**: `apps/documents/{forms,filters,tables}.py` and all four `documents/*.html` templates;
`templates/includes/_object_body.html`; `apps/comments/forms.py`; all `comments/*.html` templates;
`apps/notifications/admin.py`.

**Not compliant** (hardcoded Russian or English literals, no `gettext_lazy`/`gettext`/`{% translate %}`):
- `apps/content/enums.py` — 5 of 6 `NoteKind` values are bare strings (`NODE` is the one exception).
- `apps/content/forms.py` — `FORM_NOTE_KIND_CHOICES` mixes bare Russian strings with one `_()`-wrapped entry;
  every `label=`/`help_text=` on `NoteForm`'s extra fields (`parent`, `attachments`, `remove_attachments`); the
  `clean_attachments()` `ValidationError` is a bare f-string.
- `templates/content/{home,note_detail,note_drafts,note_form}.html` and `templates/base.html` — none `{% load
  i18n %}` or use `{% translate %}`; every visible label/button/nav string is a hardcoded Russian literal.
- `apps/comments/models.py` — two `ValidationError` messages are bare strings.
- `apps/sharing/models.py`, `apps/sharing/admin.py` — field `help_text`/form labels are bare strings.
- `static/notifications/js/notifications.js` — all UI strings (labels, empty-state text, `Intl.RelativeTimeFormat("ru", ...)`)
  are hardcoded Russian with no JS-side i18n catalog wiring (plain JS, so this needs a different mechanism than
  `gettext_lazy` — e.g. `django.views.i18n.JavaScriptCatalog` or server-rendered data attributes).

## KI-6: N+1 query in DocumentTable

*Severity: Medium (perf, scales with list-page size).* `DocumentTable.render_attachments_count`
(`apps/documents/tables.py`) calls `record.attachments.alive().count()` per row — one query per row despite
`DocumentListView.get_queryset()` (`apps/documents/views.py`) calling `.prefetch_related("attachments")`. The
`.alive()` filter isn't satisfied by the plain prefetch cache, so the prefetch only helps `tags`, not this column.

## KI-7: N+1 query on home page cover images

*Severity: Low/Medium.* `HomeView.get_queryset` (`apps/content/views.py`) issues one extra query per note (up to
10 per page load) to find each note's cover image (`note.attachments.alive().filter(kind=IMAGE)...first()`) inside
a Python list comprehension, with no `prefetch_related`/`Prefetch`.

## KI-8: autosave race can create duplicate notes

*Severity: Medium — a real, user-visible data-quality issue, and self-documented in the code's own comments.*
Two distinct causes:
1. The browser's URL only becomes the edit URL after `note_autosave.js` gets a response and calls
   `history.replaceState`. Clicking "Сохранить" (Save) *before* that response lands still POSTs to the "add"
   endpoint (`public_id=None`), creating a **second, distinct `Note` row** and orphaning the autosaved draft.
   `NoteFormView.get`'s "auto-resume" redirect (finds an existing draft under the same parent) mitigates this on
   the *next* visit, not within the same in-flight page.
2. The `navigator.sendBeacon` last-gasp save (fired on `pagehide`/tab-hide) does **not** check the in-memory
   `saving` guard the normal `fetch`-based autosave path uses — a beacon fired while a fetch-based autosave to the
   same "add" URL is still in flight can create two draft rows in one tab-close.

Neither `NoteAutosaveView` nor `_persist_note` has any idempotency key or row-level locking server-side; the only
guard is the JS-side, per-tab, in-memory `saving` boolean, which the beacon path bypasses entirely.

## KI-9: registration IP and JWT login tracking gaps

*Severity: Low.* `User.registration_ip` (`apps/users/models.py`) **now gets set** — a
`user_signed_up` receiver in `apps.users.signals` fills it when a user registers through django-allauth's signup
form (see [apps/users.md](apps/users.md)). It stays `null` for users created outside that flow (admin,
`createsuperuser`), which is expected. Separately, `apps.users.signals.update_last_login_info` only fires on
Django's session-based `user_logged_in` signal — `SimpleJWT`'s `TokenObtainPairView` never sends that signal, so
`last_login_date`/`last_login_ip` never update for JWT-only (API/WS) clients, only for session/allauth logins.
That half of the gap remains, self-documented in the code's own comments.

## KI-10: bulk restore does not scope by batch

*Severity: Low today (single-user), worth fixing before multi-user.* `SoftDeleteQuerySet.soft_delete()`
(`apps/common/managers.py`) deliberately stamps every row in a batch with the *same* `deleted_at` timestamp so a
later restore can be scoped to "exactly this batch." But `restore()` is implemented as an unconditional
`update(deleted_at=None)` over whatever queryset it's called on — it provides no such scoping itself. A careless
call (e.g. the admin's `SoftDeleteAdminMixin.restore_selected` action, which just calls `.restore()` on whatever
rows the admin operator selected) restores every trashed row in that queryset, not just one batch, unless the
caller pre-filters by the exact `deleted_at` value first.

## KI-11: weather widget is a hardcoded Vilnius forecast

*Severity: Low (cosmetic/product), worth a decision either way.* `static/content/js/weather-widget.js` calls the
free, keyless Open-Meteo API directly from the browser — no missing API key, no GeoIP dependency, fails
gracefully with a retry button. But `templates/content/home.html`'s only invocation passes no
latitude/longitude/city, so **every visitor sees the same hardcoded Vilnius, Lithuania forecast, permanently**.
Reads as a leftover demo/placeholder (the surrounding column is literally named `col-reserved` in the template)
rather than a finished, personalized feature — worth either wiring it to a real per-user location or removing it.

## KI-12: HTML sanitizer allowlist comment references sheet music, not documents

*Severity: Informational.* `src/libs/html.py`'s allowlist comment justifies keeping `table`/`pre`/`code`/
`span[class]` by saying "the spec calls for storing chord sheets and sheet-music markup" — language that doesn't
match the current "personal document/contract/warranty store" framing at all. This suggests either an earlier,
different framing of this project, or a copy-pasted comment from elsewhere. Worth a quick check that the actual
allowlist still matches the content types this project really needs today (tables/code blocks are plausible for
notes regardless, but the *reasoning* on record is stale).

## KI-13: duplicate, empty src/pytest.ini

*Severity: Informational, not a bug.* `docker-compose.yml` bind-mounts the root `./pytest.ini` and `./tests` into
the `django` container under `/app`; Docker's bind-mount behavior creates matching empty placeholder files back on
the *host* under `src/pytest.ini` (confirmed empty, untracked in git) as a side effect. Harmless, but can confuse
a newcomer or an AI agent that greps for `pytest.ini` and finds two, one of which is silently irrelevant.

## KI-14: dead fields reserved for future use

*Severity: Informational.* `Note.json_data` (schemaless `JSONField`) and `ExpiryModel.remind_at` were inert when
this was written. **Both are now partly used on `Note`** by `apps.events`: `remind_at` is the computed next
reminder fire time, and `json_data` holds the `{"system_hub": "events"}` marker on the Events hub node and
`reminded_at` after a reminder delivery. `Attachment.expires_at`/`remind_at` are still inert. Not bugs, but worth knowing they're placeholders before assuming they do something.

