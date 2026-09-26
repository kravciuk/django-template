# apps.common

Shared abstract base models, enums, the soft-delete manager/queryset, and the `purge_trash` management command
used across the rest of the project. **No models of its own, no migrations** (per its own `apps.py` docstring) —
confirmed, there is no `migrations/` directory under this app.

Full field-by-field breakdown of every abstract base class lives in
[architecture/data-model.md](../architecture/data-model.md) — this page covers the manager, admin, and management
command instead.

## `SoftDeleteQuerySet` / `SoftDeleteManager` (`managers.py`)

```python
class SoftDeleteQuerySet(models.QuerySet):
    def alive(self):     return self.filter(deleted_at__isnull=True)
    def trashed(self):   return self.filter(deleted_at__isnull=False)
    def purgeable(self, cutoff): return self.trashed().filter(deleted_at__lte=cutoff)
    def soft_delete(self):  # bulk — every row gets the *same* timestamp
        return self.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
    def restore(self):      # bulk — NOT scoped to a particular timestamp, see Known Issues
        return self.update(deleted_at=None)
```

`soft_delete()` deliberately timestamps every row in a batch identically so a later `restore()` scoped to that
exact value only undoes that one batch — but `restore()` itself doesn't enforce that scoping; see
[Known Issues](../known-issues.md#ki-10-bulk-restore-does-not-scope-by-batch).

`SoftDeleteManager = models.Manager.from_queryset(SoftDeleteQuerySet)` — **does not exclude trashed rows from
`.objects.all()` by default**. This is a deliberate departure from the common "soft-delete manager auto-hides
trashed rows" idiom seen elsewhere — don't assume `Model.objects.all()` means "only alive rows" anywhere in this
codebase.

## Admin helpers (`admin.py`)

- `TrashedFilter(admin.SimpleListFilter)` — "trash status" (`Active` / `Trashed` / `All`), **defaults to
  `"active"`** — necessary precisely because the manager itself doesn't filter by default; without this, every
  changelist using it would show trashed+active mixed together on first load.
- `SoftDeleteAdminMixin` — adds `TrashedFilter` plus three bulk actions: `soft_delete_selected`,
  `restore_selected` (inherits the `restore()` scoping caveat above), `purge_selected` (a plain hard `.delete()`,
  deliberately not routed through a model's custom `purge_stale()` — an explicit admin click is expected to
  cascade to descendants where relevant).

## `purge_trash` management command (`management/commands/purge_trash.py`)

```
python manage.py purge_trash [--older-than N] [--dry-run]
```

`--older-than` defaults to `settings.TRASH_RETENTION_DAYS` (itself defaulting to 30). Auto-discovers every
concrete `SoftDeleteModel` subclass via `apps.get_models()`, sorted by model label, and calls
`model.purge_stale(cutoff, dry_run=dry_run)` on each — this is the polymorphism point where `apps.content.Note`
plugs in tree-safe deletion (see [apps/content.md](../apps/content.md#servicespy--cascading-tree-safe-soft-delete)) instead of the base
class's plain `qs.delete()`/`qs.count()`. Prints a per-model line and a total summary; **not currently on the
Celery Beat schedule** — it's a manually or cron-invoked command today (see
[background-jobs/celery.md](../background-jobs/celery.md)).

## Enums (`enums.py`)

- `Visibility` (`PUBLIC`/`UNLISTED`/`SHARED`/`PRIVATE`) — choice labels double as short docs, e.g.
  `UNLISTED = "unlisted", "Hidden, reachable via its own direct link"`.
- `ContentFormat` (`HTML`/`MARKDOWN`/`PLAIN`) — defined here for reuse, but is really `apps.content`-specific
  vocabulary; only consumed by `Note.body_format`.
