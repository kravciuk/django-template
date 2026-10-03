/**
 * The user's date/time display formats for JS (apps.users.formats), read
 * from <html data-date-format data-hour12 data-time-zone> that
 * templates/base.html renders via the display_formats context processor.
 *
 * window.DisplayFormats:
 *   dateFormat       Django/flatpickr date pattern, e.g. "d.m.Y"
 *   shortDateFormat  the same pattern without the year, e.g. "d.m"
 *   hour12           true for a 12-hour (AM/PM) clock
 *   pickerTimeFormat flatpickr time pattern matching `hour12`
 *   formatDate(date) / formatTime(date) / formatDateTime(date)
 *       - format a Date in the profile time zone
 *   formatDateParts(year, month, day, withoutYear) - format a calendar date
 */
(function () {
    "use strict";

    var root = document.documentElement;
    var DATE_FORMAT = root.dataset.dateFormat || "Y-m-d";
    var HOUR12 = root.dataset.hour12 === "1";
    var TIME_ZONE = root.dataset.timeZone || undefined;

    function pad(value) {
        return value < 10 ? "0" + value : String(value);
    }

    function withoutYear(format) {
        // "d.m.Y" -> "d.m", "Y-m-d" -> "m-d": drop the year and its separator.
        return format
            .replace(/^[Yy][^A-Za-z]*/, "")
            .replace(/[^A-Za-z]*[Yy]$/, "")
            .replace(/[Yy][^A-Za-z]*/, "");
    }

    function formatDateParts(year, month, day, dropYear) {
        var tokens = {
            d: pad(day), j: String(day), m: pad(month), n: String(month),
            Y: String(year), y: String(year).slice(-2),
        };
        var format = dropYear ? withoutYear(DATE_FORMAT) : DATE_FORMAT;
        return format.replace(/[djmnYy]/g, function (token) { return tokens[token]; });
    }

    var partsFormatter = null;

    function partsOf(date) {
        // Wall-clock fields of `date` in the profile zone (the browser's own
        // zone if that's unknown to Intl).
        if (partsFormatter === null) {
            var options = {
                year: "numeric", month: "numeric", day: "numeric",
                hour: "numeric", minute: "numeric", hourCycle: "h23",
            };
            try {
                partsFormatter = new Intl.DateTimeFormat("en-US", Object.assign({ timeZone: TIME_ZONE }, options));
            } catch (error) {
                partsFormatter = new Intl.DateTimeFormat("en-US", options);
            }
        }
        var parts = {};
        partsFormatter.formatToParts(date).forEach(function (part) {
            parts[part.type] = parseInt(part.value, 10);
        });
        parts.hour = parts.hour % 24;
        return parts;
    }

    function formatClock(hour, minute) {
        if (!HOUR12) {
            return pad(hour) + ":" + pad(minute);
        }
        return ((hour % 12) || 12) + ":" + pad(minute) + " " + (hour < 12 ? "AM" : "PM");
    }

    function formatDate(date) {
        var parts = partsOf(date);
        return formatDateParts(parts.year, parts.month, parts.day, false);
    }

    function formatTime(date) {
        var parts = partsOf(date);
        return formatClock(parts.hour, parts.minute);
    }

    function formatDateTime(date) {
        var parts = partsOf(date);
        return formatDateParts(parts.year, parts.month, parts.day, false) + " " + formatClock(parts.hour, parts.minute);
    }

    window.DisplayFormats = {
        dateFormat: DATE_FORMAT,
        shortDateFormat: withoutYear(DATE_FORMAT),
        hour12: HOUR12,
        pickerTimeFormat: HOUR12 ? "h:i K" : "H:i",
        formatDate: formatDate,
        formatTime: formatTime,
        formatDateTime: formatDateTime,
        formatDateParts: formatDateParts,
    };
})();
