# Logging

Entirely custom (`core/logging.py::get_logging_config()`), not Django's default mechanism — both `dev.py` and
`prod.py` set `LOGGING_CONFIG = None`, and `base.py` calls `logging.config.dictConfig(LOGGING)` itself at import
time (`LOGGING = get_logging_config()` then an immediate `dictConfig(LOGGING)` call, both in `base.py`).

## Outputs

- **Console** (`console_json` handler) — human-readable, colorized in dev via `colorlog` when
  `LOG_CONSOLE_COLOR=true`, plain text otherwise. Used in both dev and prod since container stdout is the
  standard log source for `docker logs`/the `json-file` logging driver.
- **Files** — JSON, one line per record, rotating (`RotatingFileHandler`, size/count from
  `LOG_FILE_MAX_SIZE`/`LOG_FILE_BACKUP_COUNT`): `logs/django/django.log` + `django_error.log` (ERROR+),
  `logs/celery/celery.log` + `celery_error.log`.

## `JSONFormatter`

Emits a fixed field set per line: `timestamp, level, logger, message, module, function, line, user_id, client_ip,
real_ip, cf_ip_country, cf_ray, method, path, status_code, duration_ms, user_agent, referer, error`. Every one of
`user_id`/`client_ip`/`real_ip`/`cf_ip_country`/`cf_ray`/`method`/`path`/`status_code`/`duration_ms`/`user_agent`/
`referer` is expected to arrive via `extra={...}` at the log call site (typically from a request-logging
middleware). **No such middleware exists in this codebase today** — these fields will log as `null` for every
Django/`django.request` log line until one is added. `CloudflareIPFilter` just guarantees the four Cloudflare-ish
fields exist as attributes (defaulting to `None`) so `JSONFormatter` never raises `AttributeError` for a record
that skipped `extra=`.

## Filters

- **`MaskSensitiveFilter`** — redacts values for keys matching `MASK_PATTERNS` (default: `password, token,
  refresh, access, api_key, secret, credit_card`) from the log **message text itself**, via regex, before
  formatting — handles both JSON-shaped `"key": "value"` and `key=value` patterns. Applies to every handler.
  **Only scrubs the message string** — if sensitive data were ever passed via `extra={...}` and rendered by a
  custom formatter field rather than interpolated into the message, this filter would not catch it; don't log raw
  dicts as pre-formatted strings expecting this to save you retroactively (per the in-code warning).
- **`ExcludeHealthFilter`** — drops any record whose `record.path` (set via `extra=`) starts with an entry in
  `LOG_EXCLUDE_PATHS` (default `/health/, /metrics/`). Since nothing currently sets `path` via `extra=` (no
  request-logging middleware — see above), **this filter currently has no effect on `/health/` traffic** despite
  being wired in; it will start working the moment such middleware is added.

## Loggers

`django`, `django.request` (adds the error file handler), `django.db.backends` (DEBUG only when
`LOG_LEVEL=DEBUG`, else WARNING — this is why the dev container's console is full of raw SQL when
`LOG_LEVEL=DEBUG`, as seen when [verifying the stack for this review](../README.md#verification-performed-for-this-review)),
`celery`, `geoip`, `websocket`, and a catch-all `apps` logger (catches any `logging.getLogger("apps.<name>")` call
from anywhere under `apps/` — without it, such calls would propagate to Django's unconfigured root logger and be
silently dropped).

## What's missing to make the `extra=` fields actually populate

There is currently no middleware anywhere in `MIDDLEWARE` that populates `client_ip`/`real_ip`/`cf_ip_country`/
`cf_ray`/`method`/`path`/`status_code`/`duration_ms`/`user_agent`/`referer` via `extra=`. `.env.example` already
defines the Cloudflare header names (`CLOUDFLARE_HEADER_IP`, `CLOUDFLARE_HEADER_COUNTRY`, `CLOUDFLARE_HEADER_RAY`)
but **nothing in the codebase reads them** — they look like a prepared-but-unimplemented hook for a future
request-logging middleware, matching `libs/utils.py::get_client_ip`'s existing `X-Forwarded-For` handling. See
[future/feature-gaps.md](../future/feature-gaps.md).
