/**
 * Hides NoteForm calendar fields that don't apply to the current choice:
 * "Every"/"Repeat until" while "Repeat" is off (or a custom rule the simple
 * controls can't express), and the color picker while "Use the default
 * calendar color" is checked. Hidden inputs still submit - NoteForm.clean()
 * already ignores them in those states. Without this script every field
 * simply stays visible.
 */
(function () {
    "use strict";

    var CUSTOM_RECURRENCE = "CUSTOM";

    function wrapperOf(id) {
        var el = document.getElementById(id);
        // Each field is wrapped in its own .mb-3 by includes/_form_fields.html.
        return el ? el.closest(".mb-3") : null;
    }

    function bindToggle(controlId, dependentIds, isShown) {
        var control = document.getElementById(controlId);
        if (!control) {
            return;
        }
        var wrappers = dependentIds.map(wrapperOf).filter(Boolean);
        function sync() {
            var shown = isShown(control);
            wrappers.forEach(function (wrapper) {
                wrapper.hidden = !shown;
            });
        }
        control.addEventListener("change", sync);
        sync();
    }

    function init() {
        bindToggle("id_repeat", ["id_repeat_interval", "id_repeat_until"], function (select) {
            return select.value !== "" && select.value !== CUSTOM_RECURRENCE;
        });
        bindToggle("id_use_default_color", ["id_color"], function (checkbox) {
            return !checkbox.checked;
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
