/**
 * The /events/ calendar (templates/events/calendar.html): a FullCalendar 6
 * instance fed by apps.events' JSON feed, plus the quick-note modal that
 * creates/edits notes through the QuickNoteViewSet API.
 *
 * Wire conventions (see apps/events/serializers.py): all-day values are
 * plain dates with an *exclusive* end; timed values are ISO datetimes in
 * the calendar's time zone (the user's profile zone, passed in as
 * data-time-zone and also active server-side). The modal shows all-day
 * ends inclusively, as people read them, and converts on save.
 *
 * Mobile: list view by default below 768px, tap a day (dateClick) or the
 * "+" button to create, long-press + drag to select several days, swipe
 * left/right to change the period.
 */
(function () {
    "use strict";

    var script = document.currentScript;
    var FEED_URL = script ? script.dataset.feedUrl : null;
    var TAGS_URL = script ? script.dataset.tagsUrl : null;
    var NOTES_URL = script ? script.dataset.notesUrl : null;
    var TIME_ZONE = (script && script.dataset.timeZone) || "UTC";
    var HAS_PROFILE_TIME_ZONE = script && script.dataset.hasProfileTimeZone === "1";
    var NOTE_COLOR = (script && script.dataset.noteColor) || "#3a3f44";

    var MOBILE_QUERY = "(max-width: 767.98px)";
    var FILTERS_STORAGE_KEY = "events.filters";
    var SWIPE_MIN_DX = 60;
    var SWIPE_MAX_DY = 40;
    var SWIPE_MAX_MS = 350;
    // dateClick and select can both fire for one click - ignore a second
    // "open" request within this window.
    var REOPEN_GUARD_MS = 400;
    var DEFAULT_START_HOUR = "09:00";
    var DEFAULT_END_HOUR = "10:00";

    function isMobile() {
        return window.matchMedia && window.matchMedia(MOBILE_QUERY).matches;
    }

    function getCsrfToken() {
        var input = document.querySelector("input[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function apiRequest(url, method, body) {
        return fetch(url, {
            method: method,
            headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
            body: body ? JSON.stringify(body) : undefined,
        }).then(function (response) {
            if (response.status === 204) {
                return { ok: true, data: null };
            }
            return response.json().then(
                function (data) { return { ok: response.ok, data: data }; },
                function () { return { ok: response.ok, data: null }; },
            );
        });
    }

    function firstErrorMessage(data) {
        if (!data) {
            return null;
        }
        for (var key in data) {
            if (Object.prototype.hasOwnProperty.call(data, key)) {
                var value = data[key];
                return Array.isArray(value) ? String(value[0]) : String(value);
            }
        }
        return null;
    }

    // --- Plain YYYY-MM-DD / YYYY-MM-DDTHH:MM helpers (no Date objects, so
    // the browser's own zone never leaks into the calendar's zone). ---

    function addDays(isoDate, days) {
        var parts = isoDate.split("-");
        var date = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2] + days));
        return date.toISOString().slice(0, 10);
    }

    function datePart(value) {
        return value ? value.slice(0, 10) : "";
    }

    function localDateTimePart(value) {
        // "2026-10-05T10:00:00+03:00" -> "2026-10-05T10:00"
        return value && value.length > 10 ? value.slice(0, 16) : (value ? value + "T" + DEFAULT_START_HOUR : "");
    }

    function todayInCalendarZone(calendar) {
        // formatIso renders in the calendar's (named) zone, not the browser's.
        return calendar.formatIso(new Date()).slice(0, 10);
    }

    function isTouchEvent(jsEvent) {
        if (!jsEvent) {
            return false;
        }
        return (jsEvent.type || "").indexOf("touch") === 0 ||
            jsEvent.pointerType === "touch" ||
            (typeof TouchEvent !== "undefined" && jsEvent instanceof TouchEvent);
    }

    // --- RRULE <-> simple repeat controls (mirrors apps/events/recurrence.py) ---

    var FREQUENCIES = ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"];

    function parseSimpleRule(rule) {
        if (!rule) {
            return { freq: "", interval: 1, until: "" };
        }
        var parts = {};
        var chunks = rule.toUpperCase().split(";");
        for (var i = 0; i < chunks.length; i++) {
            if (!chunks[i]) {
                continue;
            }
            var pair = chunks[i].split("=");
            if (pair.length !== 2 || ["FREQ", "INTERVAL", "UNTIL"].indexOf(pair[0]) === -1) {
                return null;
            }
            parts[pair[0]] = pair[1];
        }
        if (FREQUENCIES.indexOf(parts.FREQ) === -1) {
            return null;
        }
        var until = parts.UNTIL ? parts.UNTIL.slice(0, 4) + "-" + parts.UNTIL.slice(4, 6) + "-" + parts.UNTIL.slice(6, 8) : "";
        return { freq: parts.FREQ, interval: parseInt(parts.INTERVAL || "1", 10) || 1, until: until };
    }

    function buildRule(freq, interval, until) {
        if (!freq) {
            return "";
        }
        var parts = ["FREQ=" + freq];
        if (interval > 1) {
            parts.push("INTERVAL=" + interval);
        }
        if (until) {
            parts.push("UNTIL=" + until.replace(/-/g, "") + "T235959");
        }
        return parts.join(";");
    }

    // --- Filters (persisted per browser in localStorage) ---

    function loadFilters() {
        try {
            var raw = window.localStorage.getItem(FILTERS_STORAGE_KEY);
            var parsed = raw ? JSON.parse(raw) : null;
            if (parsed && Array.isArray(parsed.sources) && Array.isArray(parsed.tags)) {
                return parsed;
            }
        } catch (error) {
            // Storage blocked or corrupt - fall back to "show everything".
        }
        return { sources: ["note", "document"], tags: [] };
    }

    function saveFilters(filters) {
        try {
            window.localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(filters));
        } catch (error) {
            // Not persisting is fine.
        }
    }

    function init() {
        var calendarEl = document.getElementById("events-calendar");
        var wrap = document.querySelector("[data-calendar-wrap]");
        if (!calendarEl || !FEED_URL || !NOTES_URL || typeof FullCalendar === "undefined") {
            return;
        }

        var filters = loadFilters();
        var modal = initModal();
        var interacting = false;
        var mobile = isMobile();

        function toolbarFor(isMobileLayout) {
            if (isMobileLayout) {
                return { left: "title", center: "", right: "today prev,next" };
            }
            return {
                left: "prev,next today addEvent",
                center: "title",
                right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek",
            };
        }

        function filterParams() {
            var params = { sources: filters.sources.join(",") };
            if (filters.tags.length) {
                params.tags = filters.tags.join(",");
            }
            return params;
        }

        var calendar = new FullCalendar.Calendar(calendarEl, {
            timeZone: TIME_ZONE,
            locale: document.documentElement.lang || "en",
            initialView: mobile ? "listWeek" : "dayGridMonth",
            headerToolbar: toolbarFor(mobile),
            customButtons: {
                addEvent: {
                    text: "+ " + gettext("Event"),
                    hint: gettext("New event"),
                    click: function () { openCreateForDay(todayInCalendarZone(calendar)); },
                },
            },
            buttonText: { listWeek: gettext("List") },
            height: mobile ? "auto" : fillHeight(),
            nowIndicator: true,
            // Day-number links would swallow taps on phones (the browser's
            // touch adjustment snaps a tap in a small cell onto the nearby
            // link) - there, a tap creates; the view <select> switches views.
            navLinks: !mobile,
            dayMaxEvents: true,
            selectable: true,
            selectMirror: true,
            editable: true,
            longPressDelay: 300,
            selectLongPressDelay: 300,
            eventLongPressDelay: 300,
            eventSources: [{
                url: FEED_URL,
                extraParams: filterParams,
                failure: function () { showLoadError(); },
            }],
            select: function (info) {
                calendar.unselect();
                if (info.allDay) {
                    openCreate(info.startStr, addDays(info.endStr, -1), true);
                } else {
                    openCreate(localDateTimePart(info.startStr), localDateTimePart(info.endStr), false);
                }
            },
            dateClick: function (info) {
                // Touch: a tap never starts a selection (that needs a long
                // press), so this is the single-tap way to create. Mouse
                // clicks are already covered by `select`.
                if (!isTouchEvent(info.jsEvent)) {
                    return;
                }
                if (info.allDay) {
                    openCreateForDay(info.dateStr);
                } else {
                    openCreate(localDateTimePart(info.dateStr), "", false);
                }
            },
            eventClick: function (info) {
                info.jsEvent.preventDefault();
                var props = info.event.extendedProps;
                if (props.source === "document") {
                    window.location.href = props.detail_url;
                    return;
                }
                openEdit(props.public_id);
            },
            eventDragStart: function () { interacting = true; },
            eventDragStop: function () { interacting = false; },
            eventResizeStart: function () { interacting = true; },
            eventResizeStop: function () { interacting = false; },
            eventDrop: persistMove,
            eventResize: persistMove,
            windowResize: function () {
                var nowMobile = isMobile();
                if (nowMobile !== mobile) {
                    mobile = nowMobile;
                    calendar.setOption("headerToolbar", toolbarFor(mobile));
                    calendar.setOption("navLinks", !mobile);
                    calendar.changeView(mobile ? "listWeek" : "dayGridMonth");
                    syncViewSelect();
                }
                calendar.setOption("height", mobile ? "auto" : fillHeight());
            },
            datesSet: syncViewSelect,
        });

        function fillHeight() {
            // Fill the viewport below the calendar's own top edge;
            // innerHeight tracks the *visible* height on mobile browsers.
            var top = wrap ? wrap.getBoundingClientRect().top + window.scrollY : 0;
            return Math.max(480, window.innerHeight - top - 24);
        }

        function showLoadError() {
            modal.flash(gettext("Couldn't load the calendar. Try reloading the page."));
        }

        function persistMove(info) {
            var event = info.event;
            var body = { all_day: event.allDay };
            if (event.allDay) {
                body.starts_at = event.startStr.slice(0, 10);
                body.ends_at = event.endStr ? event.endStr.slice(0, 10) : addDays(body.starts_at, 1);
            } else {
                body.starts_at = event.startStr;
                body.ends_at = event.endStr || null;
            }
            apiRequest(NOTES_URL + event.extendedProps.public_id + "/", "PATCH", body).then(function (result) {
                if (!result.ok) {
                    info.revert();
                    modal.flash(firstErrorMessage(result.data) || gettext("Couldn't move the event."));
                    return;
                }
                calendar.refetchEvents();
            }, function () {
                info.revert();
                modal.flash(gettext("Couldn't move the event."));
            });
        }

        // --- Create / edit through the modal ---

        var lastOpenedAt = 0;

        function guardReopen() {
            var now = Date.now();
            if (now - lastOpenedAt < REOPEN_GUARD_MS) {
                return false;
            }
            lastOpenedAt = now;
            return true;
        }

        function openCreateForDay(day) {
            openCreate(day, day, true);
        }

        function openCreate(start, end, allDay) {
            if (!guardReopen()) {
                return;
            }
            modal.open({
                public_id: null,
                title: "",
                body: "",
                body_format: "plain",
                all_day: allDay,
                start: start,
                end: end,
                recurrence: "",
                remind_minutes_before: null,
                color: "",
            });
        }

        function openEdit(publicId) {
            if (!guardReopen()) {
                return;
            }
            apiRequest(NOTES_URL + publicId + "/", "GET").then(function (result) {
                if (!result.ok || !result.data) {
                    modal.flash(gettext("Couldn't open this event."));
                    return;
                }
                var note = result.data;
                modal.open({
                    public_id: note.public_id,
                    title: note.title,
                    body: note.body,
                    body_format: note.body_format,
                    all_day: note.all_day,
                    start: note.all_day ? note.starts_at : localDateTimePart(note.starts_at),
                    end: note.all_day
                        ? (note.ends_at ? addDays(note.ends_at, -1) : "")
                        : localDateTimePart(note.ends_at),
                    recurrence: note.recurrence,
                    remind_minutes_before: note.remind_minutes_before,
                    color: note.color,
                    edit_url: note.edit_url,
                });
            });
        }

        modal.onSave = function (publicId, payload, thenOpenFullForm) {
            var url = publicId ? NOTES_URL + publicId + "/" : NOTES_URL;
            var method = publicId ? "PATCH" : "POST";
            if (!publicId && thenOpenFullForm) {
                // Born as a draft - the full form's Save publishes it, and
                // an abandoned one is cleaned up by cleanup_stale_drafts.
                payload.is_draft = true;
            }
            return apiRequest(url, method, payload).then(function (result) {
                if (!result.ok) {
                    return firstErrorMessage(result.data) || gettext("Couldn't save the event.");
                }
                if (thenOpenFullForm) {
                    window.location.href = result.data.edit_url;
                    return null;
                }
                calendar.refetchEvents();
                return null;
            }, function () {
                return gettext("Couldn't save the event.");
            });
        };

        modal.onDelete = function (publicId) {
            return apiRequest(NOTES_URL + publicId + "/", "DELETE").then(function (result) {
                if (!result.ok) {
                    return firstErrorMessage(result.data) || gettext("Couldn't delete the event.");
                }
                calendar.refetchEvents();
                return null;
            });
        };

        // --- Mobile view <select>, FAB, swipe ---

        var viewSelect = document.querySelector("[data-view-select]");

        function syncViewSelect() {
            if (viewSelect && calendar.view) {
                viewSelect.value = calendar.view.type;
            }
        }

        if (viewSelect) {
            viewSelect.addEventListener("change", function () {
                calendar.changeView(viewSelect.value);
            });
        }

        var fab = document.querySelector('[data-action="add-event"]');
        if (fab) {
            fab.addEventListener("click", function () {
                openCreateForDay(todayInCalendarZone(calendar));
            });
        }

        var touchStart = null;
        calendarEl.addEventListener("touchstart", function (event) {
            if (event.touches.length !== 1) {
                touchStart = null;
                return;
            }
            touchStart = { x: event.touches[0].clientX, y: event.touches[0].clientY, at: Date.now() };
        }, { passive: true });
        calendarEl.addEventListener("touchend", function (event) {
            if (!touchStart || interacting || !event.changedTouches.length) {
                touchStart = null;
                return;
            }
            var dx = event.changedTouches[0].clientX - touchStart.x;
            var dy = event.changedTouches[0].clientY - touchStart.y;
            var quick = Date.now() - touchStart.at <= SWIPE_MAX_MS;
            touchStart = null;
            if (quick && Math.abs(dx) >= SWIPE_MIN_DX && Math.abs(dy) <= SWIPE_MAX_DY) {
                if (dx < 0) {
                    calendar.next();
                } else {
                    calendar.prev();
                }
            }
        }, { passive: true });

        // --- Filters ---

        initFilters(filters, function () {
            saveFilters(filters);
            calendar.refetchEvents();
        });

        // --- Time zone hint ---

        var hint = document.querySelector("[data-time-zone-hint]");
        var browserZone = (typeof Intl !== "undefined" && Intl.DateTimeFormat)
            ? Intl.DateTimeFormat().resolvedOptions().timeZone
            : "";
        if (hint && !HAS_PROFILE_TIME_ZONE && browserZone && browserZone !== TIME_ZONE) {
            hint.hidden = false;
        }

        calendar.render();
        syncViewSelect();
    }

    function initFilters(filters, onChange) {
        var sourceInputs = document.querySelectorAll("[data-filter-source]");
        Array.prototype.forEach.call(sourceInputs, function (input) {
            input.checked = filters.sources.indexOf(input.dataset.filterSource) !== -1;
            input.addEventListener("change", function () {
                filters.sources = Array.prototype.filter.call(sourceInputs, function (item) {
                    return item.checked;
                }).map(function (item) { return item.dataset.filterSource; });
                onChange();
            });
        });

        var menu = document.querySelector("[data-tags-menu]");
        var button = document.querySelector("[data-tags-button]");
        if (!menu || !TAGS_URL) {
            return;
        }

        function updateButton() {
            if (button) {
                button.textContent = filters.tags.length
                    ? interpolate(gettext("Tags (%s)"), [filters.tags.length])
                    : gettext("Tags");
            }
        }

        fetch(TAGS_URL, { headers: { "X-Requested-With": "XMLHttpRequest" } })
            .then(function (response) { return response.ok ? response.json() : []; })
            .then(function (tags) {
                // Drop remembered tags that no longer exist.
                filters.tags = filters.tags.filter(function (tag) { return tags.indexOf(tag) !== -1; });
                updateButton();
                if (!tags.length) {
                    return;
                }
                var empty = menu.querySelector("[data-tags-empty]");
                if (empty) {
                    empty.remove();
                }
                tags.forEach(function (tag, index) {
                    var id = "events-tag-" + index;
                    var row = document.createElement("div");
                    row.className = "form-check";
                    var input = document.createElement("input");
                    input.className = "form-check-input";
                    input.type = "checkbox";
                    input.id = id;
                    input.checked = filters.tags.indexOf(tag) !== -1;
                    var label = document.createElement("label");
                    label.className = "form-check-label";
                    label.htmlFor = id;
                    label.textContent = tag;
                    input.addEventListener("change", function () {
                        if (input.checked) {
                            filters.tags.push(tag);
                        } else {
                            filters.tags = filters.tags.filter(function (item) { return item !== tag; });
                        }
                        updateButton();
                        onChange();
                    });
                    row.appendChild(input);
                    row.appendChild(label);
                    menu.appendChild(row);
                });
            })
            .catch(function () { /* filter stays empty; the calendar still works */ });
    }

    function initModal() {
        var el = document.getElementById("event-modal");
        var form = el.querySelector("[data-event-form]");
        var bsModal = new bootstrap.Modal(el);
        var fields = {
            title: form.querySelector("#event-title"),
            body: form.querySelector("#event-body"),
            allDay: form.querySelector("#event-all-day"),
            start: form.querySelector("#event-start"),
            end: form.querySelector("#event-end"),
            repeat: form.querySelector("#event-repeat"),
            interval: form.querySelector("#event-repeat-interval"),
            until: form.querySelector("#event-repeat-until"),
            remind: form.querySelector("#event-remind"),
            color: form.querySelector("#event-color"),
            colorDefault: form.querySelector("#event-color-default"),
        };
        var titleEl = el.querySelector("[data-modal-title]");
        var errorEl = el.querySelector("[data-error]");
        var bodyHint = el.querySelector("[data-body-hint]");
        var recurringHint = el.querySelector("[data-recurring-hint]");
        var customOption = el.querySelector("[data-custom-option]");
        var repeatDetails = el.querySelectorAll("[data-repeat-detail]");
        var deleteButton = el.querySelector('[data-action="delete"]');
        var fullFormButton = el.querySelector('[data-action="full-form"]');
        var current = null;
        var busy = false;

        var api = {
            onSave: null,
            onDelete: null,
            open: open,
            flash: flash,
        };

        function setError(message) {
            errorEl.textContent = message || "";
            errorEl.hidden = !message;
        }

        function flash(message) {
            // Errors outside the modal (feed/drag) - a plain alert keeps
            // this dependency-free and works the same on phones.
            window.alert(message);
        }

        function setAllDay(allDay) {
            // Switch the input types, carrying the value across.
            var start = fields.start.value;
            var end = fields.end.value;
            fields.start.type = allDay ? "date" : "datetime-local";
            fields.end.type = allDay ? "date" : "datetime-local";
            if (allDay) {
                fields.start.value = datePart(start);
                fields.end.value = datePart(end);
            } else {
                fields.start.value = start && start.length === 10 ? start + "T" + DEFAULT_START_HOUR : start;
                fields.end.value = end && end.length === 10 ? end + "T" + DEFAULT_END_HOUR : end;
            }
        }

        function syncRepeatDetails() {
            var show = !!fields.repeat.value && fields.repeat.value !== "CUSTOM";
            Array.prototype.forEach.call(repeatDetails, function (item) { item.hidden = !show; });
        }

        function open(data) {
            current = data;
            setError("");
            titleEl.textContent = data.public_id ? gettext("Edit event") : gettext("New event");
            fields.title.value = data.title || "";
            fields.body.value = data.body || "";
            var plainBody = data.body_format === "plain";
            fields.body.disabled = !plainBody;
            bodyHint.hidden = plainBody;

            fields.allDay.checked = !!data.all_day;
            fields.start.type = data.all_day ? "date" : "datetime-local";
            fields.end.type = data.all_day ? "date" : "datetime-local";
            fields.start.value = data.start || "";
            fields.end.value = data.end || "";

            var simple = parseSimpleRule(data.recurrence);
            customOption.hidden = customOption.disabled = simple !== null;
            if (simple === null) {
                fields.repeat.value = "CUSTOM";
                customOption.textContent = interpolate(gettext("Custom: %s"), [data.recurrence]);
            } else {
                fields.repeat.value = simple.freq;
                fields.interval.value = simple.interval;
                fields.until.value = simple.until;
            }
            syncRepeatDetails();
            recurringHint.hidden = !data.recurrence;

            var remind = data.remind_minutes_before === null || data.remind_minutes_before === undefined
                ? "" : String(data.remind_minutes_before);
            if (remind && !fields.remind.querySelector('option[value="' + remind + '"]')) {
                var option = document.createElement("option");
                option.value = remind;
                option.textContent = interpolate(gettext("%s minutes before"), [remind]);
                fields.remind.appendChild(option);
            }
            fields.remind.value = remind;

            fields.colorDefault.checked = !data.color;
            fields.color.value = data.color || NOTE_COLOR;

            deleteButton.hidden = !data.public_id;
            bsModal.show();
        }

        function payload() {
            var allDay = fields.allDay.checked;
            var start = fields.start.value || null;
            var end = fields.end.value || null;
            if (allDay && end) {
                end = addDays(end, 1); // inclusive in the modal, exclusive on the wire
            } else if (allDay && start && !end) {
                end = addDays(start, 1);
            }
            var data = {
                title: fields.title.value.trim(),
                all_day: allDay,
                starts_at: start,
                ends_at: end,
                remind_minutes_before: fields.remind.value === "" ? null : parseInt(fields.remind.value, 10),
                color: fields.colorDefault.checked ? "" : fields.color.value,
            };
            if (!fields.body.disabled) {
                data.body = fields.body.value;
            }
            if (fields.repeat.value !== "CUSTOM") {
                data.recurrence = buildRule(
                    fields.repeat.value,
                    parseInt(fields.interval.value, 10) || 1,
                    fields.until.value,
                );
            }
            return data;
        }

        function submit(thenOpenFullForm) {
            if (busy || !api.onSave) {
                return;
            }
            if (!fields.title.value.trim()) {
                setError(gettext("Enter a title."));
                fields.title.focus();
                return;
            }
            busy = true;
            setError("");
            api.onSave(current.public_id, payload(), thenOpenFullForm).then(function (error) {
                busy = false;
                if (error) {
                    setError(error);
                    return;
                }
                if (!thenOpenFullForm) {
                    bsModal.hide();
                }
            });
        }

        fields.allDay.addEventListener("change", function () { setAllDay(fields.allDay.checked); });
        fields.repeat.addEventListener("change", syncRepeatDetails);
        fields.color.addEventListener("input", function () { fields.colorDefault.checked = false; });
        form.addEventListener("submit", function (event) {
            event.preventDefault();
            submit(false);
        });
        fullFormButton.addEventListener("click", function () { submit(true); });
        deleteButton.addEventListener("click", function () {
            if (!current || !current.public_id || busy || !api.onDelete) {
                return;
            }
            if (!window.confirm(gettext("Delete this event? It goes to the trash and can be restored."))) {
                return;
            }
            busy = true;
            api.onDelete(current.public_id).then(function (error) {
                busy = false;
                if (error) {
                    setError(error);
                    return;
                }
                bsModal.hide();
            });
        });
        el.addEventListener("shown.bs.modal", function () {
            // Phones: don't pop the keyboard up over the dates right away.
            if (!isMobile()) {
                fields.title.focus();
            }
        });

        return api;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
