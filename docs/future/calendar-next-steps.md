# Календарь: следующие этапы

Что сознательно не вошло в первую версию `/events/` (см. [apps/events.md](../apps/events.md)) и как это лучше
сделать дальше.

## ICS-подписка (односторонняя синхронизация)

Адрес вида `/events/feed/<token>.ics` только для чтения, на который можно подписаться в Google Calendar, Apple
Calendar или в телефоне. Это первый и самый дешёвый шаг к синхронизации: OAuth не нужен.

- Нужен секретный токен на пользователя, то есть поле в `User` или отдельная модель с возможностью перевыпуска.
  Это миграция.
- Источник данных: `apps.events.services.calendar_entries()`. Повторяющиеся события лучше отдавать как
  `RRULE`, а не разворачивать: формат `Note.recurrence` уже совместим.
- `UID` = `Note.public_id`, `DTSTAMP` = `updated_at`, all-day = `VALUE=DATE` с исключающим `DTEND`.
  Это та же конвенция, что в API.

## Синхронизация с Google Calendar — сделано

Двусторонняя синхронизация реализована в `apps/events/google/` (см. [apps/events.md](../apps/events.md#google-calendar-sync-google)
и [operations/google-calendar.md](../operations/google-calendar.md)). Вместо allauth и `Note.json_data` использованы
собственный OAuth (PKCE) и отдельные модели `GoogleCalendarAccount`/`GoogleEventLink`.

Что можно сделать дальше:
- ~~**Push-уведомления** (`events.watch`)~~ — сделано: `google/watch.py`, `google/webhook.py`, см.
  [operations/google-calendar.md](../operations/google-calendar.md#5-push-notifications).
- **Несколько календарей** на пользователя: вынести `calendar_id`/`sync_token` в отдельную модель подписки.
  Ссылки уже хранят `calendar_id`.
- **Исключения повторений** (см. следующий раздел): тогда из Google можно будет импортировать
  `recurringEventId`/`originalStartTime`, которые сейчас пропускаются.

## Исключения для отдельных повторений

Сейчас повторяющееся событие редактируется только целиком, а перетаскивать отдельные повторения нельзя. Чтобы
можно было «изменить или удалить только это повторение», понадобятся `EXDATE` (удалённые даты) и переопределения
(отдельные заметки со ссылкой на серию и исходной датой повторения, аналог `recurringEventId` и
`originalStartTime` в Google).

## Вид и дата в URL

`?view=week&date=2026-10-05`: календарь остаётся на той же позиции после перезагрузки и кнопки «назад», и на
конкретную неделю можно дать ссылку. Это небольшая доработка `calendar.js` (`datesSet` → `history.replaceState`).

## Язык напоминаний

Тексты напоминаний собираются на языке по умолчанию: у Celery нет языка пользователя. Если понадобятся
локализованные напоминания, язык пользователя нужно сохранять (например, в `User.json_data` при смене языка) и
включать через `translation.override()` в `send_due_reminders`.
