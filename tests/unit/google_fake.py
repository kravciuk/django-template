"""In-memory stand-in for apps.events.google.client.CalendarClient - the
same methods, with Google's observable behavior the sync relies on: etags
and `updated` bump on every write, deleted events stay as "cancelled" (and
their ids stay taken -> 409), incremental listing via sync tokens, 410 on
an expired token, PATCH merging objects with null clearing a field.
"""
import copy
import itertools
from datetime import UTC, datetime, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.events.google.client import Conflict, NotFound, SyncTokenExpired


def _merge(target, patch):
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


class FakeGoogleCalendar:
    def __init__(self, calendars=None):
        self.calendars = calendars or [
            {"id": "me@example.com", "summary": "me@example.com", "primary": True, "accessRole": "owner"},
            {"id": "work@group.calendar.google.com", "summary": "Work", "accessRole": "owner"},
        ]
        self.events = {}        # (calendar_id, event_id) -> event
        self.changes = []       # (seq, calendar_id, event_id)
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)
        self.writes = []        # (method, calendar_id, event_id, body)
        self.expire_sync_tokens = False
        self.fail_with = None   # exception instance raised by every call
        self.calls = 0          # every API call, reads included
        self.channels = {}      # channel id -> watch request (+ resourceId)
        self.stopped = []       # (channel id, resource id)
        self.watch_fail_with = None
        # Google's clock: always after anything saved before the call.
        self.clock_offset = timedelta(seconds=1)

    # -- helpers for tests --

    def _now(self):
        return (timezone.now() + self.clock_offset).astimezone(UTC)

    def _touch(self, calendar_id, event):
        seq = next(self._seq)
        event["etag"] = f'"{seq}"'
        event["updated"] = self._now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.changes.append((seq, calendar_id, event["id"]))

    def add_remote(self, calendar_id, event):
        """An event created by the user in Google."""
        event = copy.deepcopy(event)
        event.setdefault("id", f"g{next(self._ids):04d}x")
        event.setdefault("status", "confirmed")
        event.setdefault("organizer", {"self": True})
        self._touch(calendar_id, event)
        self.events[(calendar_id, event["id"])] = event
        return event

    def edit_remote(self, calendar_id, event_id, **fields):
        event = self.events[(calendar_id, event_id)]
        _merge(event, fields)
        self._touch(calendar_id, event)
        return event

    def delete_remote(self, calendar_id, event_id):
        event = self.events[(calendar_id, event_id)]
        event["status"] = "cancelled"
        self._touch(calendar_id, event)

    def get(self, calendar_id, event_id):
        return self.events.get((calendar_id, event_id))

    def live(self, calendar_id):
        return [e for (cal, _id), e in self.events.items() if cal == calendar_id and e.get("status") != "cancelled"]

    def _check(self):
        self.calls += 1
        if self.fail_with is not None:
            raise self.fail_with

    # -- CalendarClient API --

    def list_calendars(self):
        self._check()
        return copy.deepcopy(self.calendars)

    def list_events(self, calendar_id, *, sync_token=None, time_min=None, page_token=None):
        self._check()
        if sync_token:
            if self.expire_sync_tokens:
                self.expire_sync_tokens = False
                raise SyncTokenExpired("Gone", 410)
            since = int(sync_token.split("-")[1])
            ids = {event_id for seq, cal, event_id in self.changes if cal == calendar_id and seq > since}
            items = [self.events[(calendar_id, event_id)] for event_id in sorted(ids)]
        else:
            items = [e for (cal, _id), e in self.events.items() if cal == calendar_id]
            if time_min is not None:
                items = [e for e in items if self._ends_after(e, time_min)]
        last = self.changes[-1][0] if self.changes else 0
        return {"items": copy.deepcopy(items), "nextSyncToken": f"tok-{last}"}

    @staticmethod
    def _ends_after(event, moment):
        if event.get("recurrence"):
            return True
        end = event.get("end") or {}
        if end.get("date"):
            return parse_date(end["date"]) > moment.astimezone(UTC).date()
        return parse_datetime(end["dateTime"]) >= moment

    def get_event(self, calendar_id, event_id):
        self._check()
        event = self.events.get((calendar_id, event_id))
        if event is None:
            raise NotFound("Not found", 404)
        return copy.deepcopy(event)

    def insert_event(self, calendar_id, body):
        self._check()
        event = copy.deepcopy(body)
        event.setdefault("id", f"g{next(self._ids):04d}x")
        if (calendar_id, event["id"]) in self.events:
            raise Conflict("Conflict", 409)
        event["status"] = "confirmed"
        event["organizer"] = {"self": True}
        if "reminders" not in event:
            event["reminders"] = {"useDefault": True}
        self._touch(calendar_id, event)
        self.events[(calendar_id, event["id"])] = event
        self.writes.append(("insert", calendar_id, event["id"], copy.deepcopy(body)))
        return copy.deepcopy(event)

    def patch_event(self, calendar_id, event_id, body):
        self._check()
        event = self.events.get((calendar_id, event_id))
        if event is None:
            raise NotFound("Not found", 404)
        _merge(event, body)
        self._touch(calendar_id, event)
        self.writes.append(("patch", calendar_id, event_id, copy.deepcopy(body)))
        return copy.deepcopy(event)

    def delete_event(self, calendar_id, event_id):
        self._check()
        event = self.events.get((calendar_id, event_id))
        if event is None or event.get("status") == "cancelled":
            return
        event["status"] = "cancelled"
        self._touch(calendar_id, event)
        self.writes.append(("delete", calendar_id, event_id, None))

    def watch_events(self, calendar_id, *, channel_id, token, address, ttl_seconds):
        self._check()
        if self.watch_fail_with is not None:
            raise self.watch_fail_with
        resource_id = f"res-{calendar_id}"
        expiration = int((timezone.now() + timedelta(seconds=ttl_seconds)).timestamp() * 1000)
        self.channels[channel_id] = {
            "calendar_id": calendar_id, "token": token, "address": address, "ttl_seconds": ttl_seconds,
            "resourceId": resource_id,
        }
        return {"kind": "api#channel", "id": channel_id, "resourceId": resource_id, "expiration": str(expiration)}

    def stop_channel(self, channel_id, resource_id):
        self._check()
        self.channels.pop(channel_id, None)
        self.stopped.append((channel_id, resource_id))


def timed(start, end, tz="Europe/Vilnius"):
    return {"start": {"dateTime": start, "timeZone": tz}, "end": {"dateTime": end, "timeZone": tz}}


def all_day(start, end_exclusive):
    return {"start": {"date": start}, "end": {"date": end_exclusive}}


def utc(*args):
    return datetime(*args, tzinfo=UTC)
