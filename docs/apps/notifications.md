# apps.notifications

An in-app notification inbox: a REST API for history/read-state, a Celery-beat retention job, and live delivery
over a Django Channels WebSocket. Full WebSocket routing/auth detail lives in
[api/websockets.md](../api/websockets.md) — this page covers the model, business logic, and REST surface.

## Model (`models.py`, `enums.py`)

`Notification(TimeStampedModel)`:

| Field | Notes |
|---|---|
| `recipient` | FK, `CASCADE`. |
| `sender` | FK, nullable, `SET_NULL` — `null` means "system/task-generated." |
| `kind` | `NotificationKind` (`SYSTEM`/`TASK`/`MESSAGE`) — drives icon/grouping client-side only; `sender IS NULL` is the actual system-vs-user signal, not `kind`. |
| `payload` | `JSONField(default=dict)` — free-form per-kind shape. |
| `content_type`/`object_id`/`target` | Optional `GenericForeignKey` back to whatever the notification concerns. |
| `is_read`, `read_at` | Composite index `(recipient, is_read, created_at)` matches both the inbox-list and retention-cleanup query shapes. |

`Meta.ordering = ["-created_at"]`. `mark_read()` is idempotent (no-op if already read).

## Creation (`services.py`)

```python
def notify(recipient, *, kind, payload, sender=None, target=None): ...
```

The single entry point for creating a notification. Registers the WebSocket push via
`transaction.on_commit(...)` — so a push only fires after the surrounding DB transaction actually commits,
avoiding a push for a row a caller might still roll back.

## REST API (`api.py`, `serializers.py`)

`NotificationViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet)` — list/retrieve/delete, plus custom
actions `mark_read`, `mark_all_read`, `unread_count`. No `permission_classes` override (project default
`IsAuthenticated`). `get_queryset()` = `Notification.objects.filter(recipient=self.request.user)
.select_related("sender")` — every action is built on top of this, so a user can only ever see/act on their own
notifications; `select_related` avoids an N+1 from the serializer's sender-display lookup. The serializer is
fully read-only (`read_only_fields = fields`) — creation only ever happens via `services.notify()`, never through
this API.

## Admin "Send notification" (`admin.py`, `forms.py`)

`NotificationAdmin` injects a "Send notification" link into its own changelist, backed by a custom `send/` admin
URL (staff/permission-gated the same as the rest of admin). `SendNotificationForm.recipient` is
`ModelChoiceField(queryset=User.objects.all())` — **any staff user with access to this admin page can message any
user account**, with no further scoping — reasonable for a trusted-staff-only tool, but worth knowing explicitly
(see [security-considerations.md](../security-considerations.md#sec-6-admin-send-notification-has-no-recipient-scoping)). `kind`/`sender` are hardcoded
(`MESSAGE`, the submitting staff user) — not attacker-controllable via the form itself.

## Retention (`tasks.py`)

Celery task `apps.notifications.tasks.cleanup_old_notifications` (Beat schedule, daily 04:00):

```python
Notification.objects.filter(is_read=True, created_at__lte=cutoff).delete()  # hard delete
```

`cutoff = now() - NOTIFICATIONS_RETENTION_DAYS` (default 90). Filters on `created_at`, **not** `read_at` — a
notification read the same day it was created and one read 89 days after creation both age out based on
*creation* date. Unread notifications are never purged by age alone, matching the documented design — worth
double-checking this is the intended product behavior (age-since-creation vs. age-since-read) if it's ever
revisited.

## Frontend (`static/notifications/js/notifications.js`)

Bell dropdown: badge count + list, backed by the REST endpoints plus a live WebSocket feed
(`connectWebSocket` — see [api/websockets.md](../api/websockets.md) for exactly how it authenticates). Reconnects
on `onclose` with a flat 3s retry (no backoff/jitter/cap) unless the close code was `4401` (unauthenticated —
deliberately does not retry). All notification text is escaped via a local `esc()` helper before `innerHTML`
insertion — XSS-safe. UI strings are hardcoded Russian literals with no i18n-catalog wiring (plain JS, so
`gettext_lazy` doesn't apply directly, but see [Known Issues](../known-issues.md#ki-5-missing-i18n-wrapping) for
the broader pattern this fits into).
