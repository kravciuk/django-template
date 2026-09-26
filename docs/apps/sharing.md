# apps.sharing

Data model and access-control logic for public share links. **The public-facing redemption view does not exist**
— see the security notes below. This is the single most important gap to know about before building on top of
this app.

## Model (`models.py`)

`ShareLink(TimeStampedModel, OwnedModel)`:

| Field | Notes |
|---|---|
| `content_type`/`object_id`/`target` | `GenericForeignKey` to any `ShareableMixin` model (`Note`, `Attachment`). |
| `token` | `secrets.token_urlsafe(32)` — 256 bits of CSPRNG entropy, URL-safe base64. Not sequential, not UUID4 — about as unguessable as it gets; brute force is infeasible on its own. |
| `password` | Optional, hashed via Django's `make_password`/`check_password` — never stored plain. Empty password → `check_password` always passes. |
| `expires_at`, `max_uses`/`used_count`, `is_active` | Usage cap + manual revocation + expiry. |
| `comment` | Free-text admin note (who it was issued to, and why). |

`is_valid()` checks `is_active`, expiry, and the usage cap — **does not** check whether the shared target itself
still exists / is soft-deleted (see below). `register_use()` increments `used_count` via `F("used_count") + 1`
(race-safe on its own), but is called *after* a separate `is_valid()` check by the (currently nonexistent) caller
— a check-then-act gap that could let concurrent redemptions slightly overshoot `max_uses`. Low severity for a
single-owner app.

`ShareableMixin` (`mixins.py`) is a trivial abstract mixin adding the `share_links` `GenericRelation` — there is
**no view-level permission mixin** in this app, despite the filename suggesting one; all authorization logic
lives in `access.py` as a plain function.

## Access control (`access.py`)

`resolve_token(token, raw_password=None)` — looks up a `ShareLink` by exact token, checks `is_valid()` and the
password if set, returns the link or `None`. Deliberately does **not** call `register_use()` itself (left to the
caller, per its own docstring) — moot today since nothing calls it.

`can_view(obj, user, *, share_link=None)` — the single access-control chokepoint used by `apps.content`,
`apps.documents`, and `apps.attachments` views. Order: owner → always allowed; draft → owner-only regardless of
visibility; `PUBLIC` → allowed; `UNLISTED` → allowed (security-through-unguessable-`public_id`); `SHARED` →
`share_link is not None and share_link.is_valid()`; else deny.

## The gap: `Visibility.SHARED` cannot currently be reached by anyone

`apps/sharing/urls.py` has exactly one path, and it's commented out:

```python
# path("<str:token>/", views.ShareLinkView.as_view(), name="resolve")
```

There is **no `views.py` file in this app at all**. `core/urls.py` mounts `path("s/", include("apps.sharing.urls"))`,
which resolves to an empty urlpatterns list. No call site anywhere in the codebase calls `resolve_token()` or
passes `share_link=` into `can_view()`. A `ShareLink` row can be created today (via the `ShareLinkInline` on
`NoteAdmin`/`AttachmentAdmin`), but **there is no URL a recipient can visit to redeem it** — `SHARED`-visibility
objects are unreachable by anyone but their owner until this view is built. See
[security-considerations.md](../security-considerations.md#sec-1-sharing-is-entirely-non-functional-today) for
the full writeup, and [security-considerations.md](../security-considerations.md#sec-2-can_view-doesnt-bind-a-share-link-to-its-target-object) /
[SEC-3](../security-considerations.md#sec-3-sharelink-validity-never-checks-whether-the-target-is-soft-deleted) for two latent bugs (`share_link`↔`obj` binding, and soft-delete
checking) that must be fixed **while** building that view, not after.

## Admin (`admin.py`)

`ShareLinkForm` — the hashed `password` column is excluded from the form entirely; a `raw_password` field goes
through `ShareLink.set_password()` on save instead, so the hash is never edited directly. `ShareLinkInline`
(reused by `NoteAdmin`/`AttachmentAdmin`) exposes `token`/`raw_password`/`is_active`/`expires_at`/`max_uses`/
`used_count`/`comment`.
