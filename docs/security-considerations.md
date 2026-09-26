# Security considerations

Security-relevant findings from this review, most important first. This is written for a single-owner deployment
today, with explicit notes on what changes once the project becomes multi-user (the owner's stated direction).

## SEC-1: sharing is entirely non-functional today

`apps/sharing/urls.py`'s only path is commented out, and there is **no `views.py` in the app at all**. No code
anywhere calls `resolve_token()` or passes `share_link=` into `can_view()`. A `ShareLink` can be created via the
admin (`ShareLinkInline` on `NoteAdmin`/`AttachmentAdmin`), but there is no URL a recipient can visit to redeem
it. `Visibility.SHARED` objects are reachable by their owner only. Not an exploitable vulnerability by itself
(the feature simply doesn't work), but it means the "backend scaffolding" should not be assumed to be
production-ready — the two bugs below (SEC-2, SEC-3) must be fixed **as part of** building the redemption view,
not discovered afterward. See [apps/sharing.md](apps/sharing.md).

## SEC-2: `can_view()` doesn't bind a share link to its target object

`apps/sharing/access.py::can_view()`'s `SHARED` branch only checks `share_link.is_valid()` — it never verifies
`share_link.content_type_id`/`object_id` actually match the object being checked (`obj`). As written today this
is unreachable (nothing calls `can_view(..., share_link=...)` at all — see SEC-1), but it is a landmine for
whoever implements the redemption view: without an explicit
`share_link.content_type == ContentType.objects.get_for_model(obj) and share_link.object_id == obj.pk` check, a
valid link minted for object A would also grant access to any other `SHARED`-visibility object B if a future
caller ever passed the wrong link in (e.g. a bug in how the redemption view resolves "the current object" vs.
"the token in the URL"). **Fix this at the same time the redemption view is written**, not as a follow-up.

## SEC-3: `ShareLink` validity never checks whether the target is soft-deleted

Neither `ShareLink.is_valid()` nor `resolve_token()` nor `can_view()` checks whether the shared target has been
soft-deleted. Every other access path in the app explicitly filters through `.alive()` at the queryset level
(e.g. `NoteDetailView` does `get_object_or_404(Note.objects.alive(), ...)`), but a `GenericForeignKey`
(`share_link.target`) does not go through any manager filtering at all. Once a redemption view exists, if it
follows `link.target` directly rather than re-fetching via `Model.objects.alive().get(pk=...)`, a share link to a
trashed note/document/attachment would keep working for the entire `TRASH_RETENTION_DAYS` window (default 30
days) after deletion. **Must be handled explicitly** in the future redemption view.

## SEC-4: no content/magic-byte validation on uploads

`apps/attachments/validators.py::validate_upload_extension` checks only the filename's extension (lower-cased)
against `ATTACHMENTS_ALLOWED_EXTENSIONS` — **no file-content/magic-byte sniffing anywhere**. `mime_type` is also
derived from the filename (`mimetypes.guess_type`), used only for display/classification, never for validation.
`ATTACHMENTS_ALLOWED_EXTENSIONS` defaults to an **empty list, meaning no restriction at all** — under default
config, any file type can be uploaded, gated only by the 25 MB size cap. Storage uses a fully randomized filename
(`uuid4().hex`), and downloads are served via `FileResponse`, which keeps today's practical RCE risk low — but the
validation gap itself is real. If `ATTACHMENTS_ALLOWED_EXTENSIONS` is ever configured (as `.env.example` already
suggests: `pdf,doc,docx,xls,xlsx,ppt,pptx,odt,ods,odp,txt,csv,rtf`), it is still only an extension check, not a
content check — a script renamed to `invoice.pdf` passes. Recommend adding a lightweight content-type check (e.g.
`python-magic`/first-bytes sniffing) alongside the extension check, at minimum for the common Office/PDF formats
this app expects.

## SEC-5: SSRF in link favicon fetching

`apps/links/services.py::fetch_favicon()` performs a server-side `GET` to
`http(s)://<user-submitted-host>/favicon.ico` with **no private/loopback/link-local/cloud-metadata IP blocklist**
and no DNS-rebinding protection; `requests`' default `allow_redirects=True` means a redirect to an internal
address is followed transparently even if a pre-connect hostname check existed. Mitigating factors already in
place: a 5-second timeout, a 300 KB streamed size cap, and a requirement that the response actually parse as an
image (`PIL.Image.verify()`) — which limits (but doesn't eliminate) impact to a host/port-reachability oracle and
the ability to persist an internally-served image into `var/media`. Low severity today (single owner, effectively
attacking their own server), but becomes a real concern the moment a second, less-trusted user can save a
bookmark — any user's saved URL becomes an SSRF primitive against the Django host's network. **Recommended fix**
(do this before multi-user launch): restrict `scheme` to `{"http", "https"}` explicitly, resolve the hostname and
reject loopback/link-local/private/multicast ranges (including `169.254.169.254`) *after* DNS resolution (to
defend against rebinding), and either disable redirects or re-validate the target after following one.

## SEC-6: admin "Send notification" has no recipient scoping

`apps/notifications/forms.py::SendNotificationForm.recipient` is `ModelChoiceField(queryset=User.objects.all())`
— any staff user with access to this admin page can send a `MESSAGE`-kind notification to **any** user account in
the system, with no further restriction. Reasonable for a small, trusted-staff-only admin tool as it exists today;
worth documenting explicitly and revisiting the scope of "who can send to whom" once there are non-staff users
whose accounts staff shouldn't necessarily be able to message freely.

## SEC-7: JWT in WebSocket query string would hit nginx access logs

`docker/nginx/nginx.conf`'s `location /ws/` block has no `access_log off` (unlike `/static/`/`/media/`) and no
scrubbing `log_format` — nginx's default `combined` format logs the full request line, including a `?token=<JWT>`
query string. The shipped browser client (`notifications.js`) never sends `?token=` (it authenticates via session
cookie only), so this is **currently latent**, not actively exploited — but `apps.notifications.ws_auth`'s JWT
fallback exists specifically for a future non-browser client, and any such client's access token would land in
plaintext in nginx access logs the moment it's used. Fix before shipping any client that relies on the `?token=`
fallback: either move the token to a different transport (subprotocol/header-equivalent) or add
`access_log off`/a scrubbing `log_format` to the `/ws/` location first.

## SEC-8: multi-user readiness — what was checked and found already correct

Spot-checked across `apps.content`, `apps.documents`, `apps.attachments`, `apps.links`, `apps.notifications`,
`apps.comments` for the classic single-user-to-multi-tenant bug pattern (a missing `owner=request.user` filter, a
`User.objects.first()` shortcut, a global queryset that should have been scoped): **no missing-filter bug was
found** — every list/detail/API view that should be owner-scoped already is. Two deliberate, documented exceptions
that are **not** bugs but should be reconsidered before multi-user launch:
- `apps.content.views.tag_suggest` searches tag names **globally across all users' notes** (explicitly flagged
  in-code as a known single-user-era tradeoff) — becomes a cross-user information leak (enumerable tag vocabulary)
  once multi-user.
- `apps.comments`' permission model lets **any authenticated user comment on any other user's `PUBLIC`-visibility
  content** — reads as an intentional blog-style design choice, but confirm it's actually wanted before multi-user.

## SEC-9: TOCTOU race on `ShareLink.max_uses`

`ShareLink.is_valid()` (checks the usage cap) and `register_use()` (increments it, race-safe via `F()` on its
own) are called as two separate steps by whatever future caller redeems a link — there's no atomic
check-and-increment. Concurrent redemptions of the same link could slightly overshoot `max_uses`. Low severity
(worst case: a couple of extra redemptions past the configured cap), but worth an atomic
`select_for_update()`/conditional-update pattern when the redemption view is built.

## SEC-10: `COMMENTS_MAX_DEPTH` vs. hardcoded DB constraint

`Comment.depth` is enforced twice: dynamically in `Comment.clean()` (reads the live `COMMENTS_MAX_DEPTH` setting,
default 5) and by a **hardcoded** DB `CheckConstraint` (`depth BETWEEN 1 AND 5`). Lowering the setting is safe;
**raising it above 5 without a matching migration** would pass application-level validation but fail at the
database with a raw `IntegrityError` instead of a friendly form error. Not currently a bug (nobody has changed the
setting), but a footgun for whoever does.
