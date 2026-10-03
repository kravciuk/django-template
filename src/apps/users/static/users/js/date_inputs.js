/**
 * Replaces native <input type="date"> / <input type="datetime-local"> with
 * flatpickr pickers that show and accept the user's profile date/time
 * format (window.DisplayFormats, see display_formats.js). Native inputs
 * always follow the browser/OS locale, which a page can't change.
 *
 * The original input stays in the form (hidden) and keeps submitting the
 * same ISO value as before ("2026-10-05" / "2026-10-05T14:30"), so no
 * server code changes; flatpickr's visible "alt" input shows the user's
 * format. Phones get the same picker (disableMobile) - their native one
 * would ignore the profile format again. If flatpickr didn't load, the
 * native inputs are left alone.
 *
 * Loaded by templates/includes/_date_inputs.html. Enhances every matching
 * input on DOMContentLoaded (opt out with data-native-picker); scripts that
 * change an input's kind or value later use window.DateInputs.
 */
(function () {
    "use strict";

    var ISO_DATE = "Y-m-d";
    var ISO_DATETIME = "Y-m-d\\TH:i";
    var SELECTOR = 'input[type="date"]:not([data-native-picker]), input[type="datetime-local"]:not([data-native-picker])';

    function formats() {
        return window.DisplayFormats || { dateFormat: "Y-m-d", hour12: false, pickerTimeFormat: "H:i" };
    }

    function available() {
        return typeof window.flatpickr === "function";
    }

    function locale() {
        var lang = (document.documentElement.lang || "").toLowerCase();
        var l10ns = window.flatpickr.l10ns || {};
        return l10ns[lang] || l10ns[lang.split("-")[0]] || "default";
    }

    function create(input, kind) {
        var withTime = kind === "datetime";
        var display = formats();
        input.dataset.dateKind = kind;
        input.type = "text";
        return window.flatpickr(input, {
            enableTime: withTime,
            time_24hr: !display.hour12,
            dateFormat: withTime ? ISO_DATETIME : ISO_DATE,
            altInput: true,
            altInputClass: input.className,
            altFormat: withTime ? display.dateFormat + " " + display.pickerTimeFormat : display.dateFormat,
            allowInput: true,
            disableMobile: true,
            locale: locale(),
        });
    }

    function kindOf(input) {
        return input.type === "datetime-local" ? "datetime" : "date";
    }

    function enhance(root) {
        if (!available()) {
            return;
        }
        Array.prototype.forEach.call((root || document).querySelectorAll(SELECTOR), function (input) {
            if (!input._flatpickr) {
                create(input, kindOf(input));
            }
        });
    }

    function setKind(input, kind) {
        var picker = input._flatpickr;
        if (!picker) {
            input.type = kind === "datetime" ? "datetime-local" : "date";
            return;
        }
        if (input.dataset.dateKind === kind) {
            return;
        }
        // flatpickr builds its time controls once - switching date <->
        // date+time means a fresh instance.
        var value = input.value;
        picker.destroy();
        input.value = value;
        create(input, kind);
    }

    function setValue(input, value) {
        var picker = input._flatpickr;
        if (!picker) {
            input.value = value || "";
            return;
        }
        if (value) {
            picker.setDate(value, false, input.dataset.dateKind === "datetime" ? ISO_DATETIME : ISO_DATE);
        } else {
            picker.clear(false);
        }
    }

    window.DateInputs = { enhance: enhance, setKind: setKind, setValue: setValue };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function () { enhance(document); });
    } else {
        enhance(document);
    }
})();
