"""Two-way Google Calendar sync - see docs/apps/events.md#google-calendar-sync.

crypto (token encryption) -> credentials (which OAuth client: the user's
own or the site-wide one) -> client (HTTP: OAuth + Calendar API) ->
mapping (Note <-> Google event) -> sync (pull/push/merge) -> views (OAuth +
settings page). Kept import-light: apps.events.models imports crypto.
"""
