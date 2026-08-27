/**
 * Background autosave for note_form.html (content:note_add / content:note_edit).
 *
 * Periodically POSTs the form's current field values to NoteAutosaveView,
 * which persists them into the very same Note row the form represents (a
 * brand-new note is created on the first tick and marked a draft, an
 * existing note is just updated in place - see apps/content/views.py).
 *
 * Attachments are never part of this - the multi-file input and the
 * "remove attachments" checkboxes stay a final-submit-only concern.
 *
 * Progressive enhancement: if this script fails entirely, the page behaves
 * exactly as it does without it - nothing about the plain "Сохранить"
 * submit flow depends on autosave having ever run.
 */
(function () {
    "use strict";

    // Captured at parse time, while document.currentScript is still valid
    // (works for a statically-included <script defer> tag).
    var INITIAL_AUTOSAVE_URL = document.currentScript ? document.currentScript.dataset.autosaveUrl : null;
    var STATUS_EL_ID = document.currentScript ? document.currentScript.dataset.statusEl : null;

    var DEBOUNCE_MS = 2000;
    var POLL_MS = 15000;

    function init() {
        var form = document.getElementById("note-form");
        if (!form || !INITIAL_AUTOSAVE_URL) {
            return;
        }

        var statusEl = STATUS_EL_ID ? document.getElementById(STATUS_EL_ID) : null;
        var autosaveUrl = INITIAL_AUTOSAVE_URL;
        var lastSnapshot = null;
        var saving = false;
        var debounceTimer = null;

        function getCsrfToken() {
            var input = form.querySelector("[name=csrfmiddlewaretoken]");
            return input ? input.value : "";
        }

        function setStatus(text) {
            if (statusEl) {
                statusEl.textContent = text;
            }
        }

        function formatTime(isoString) {
            try {
                return new Date(isoString).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            } catch (error) {
                return "";
            }
        }

        // Collects every plain form field (title, kind, body_format, body,
        // visibility, tags, parent), skipping files and attachment removal
        // checkboxes - autosave never touches attachments.
        function buildParams() {
            var params = new URLSearchParams();
            for (var i = 0; i < form.elements.length; i++) {
                var el = form.elements[i];
                if (!el.name || el.disabled) {
                    continue;
                }
                if (el.type === "file" || el.name === "remove_attachments" || el.name === "csrfmiddlewaretoken") {
                    continue;
                }
                if (el.type === "checkbox" || el.type === "radio") {
                    if (el.checked) {
                        params.append(el.name, el.value);
                    }
                    continue;
                }
                if (el.tagName === "SELECT" && el.multiple) {
                    for (var j = 0; j < el.options.length; j++) {
                        if (el.options[j].selected) {
                            params.append(el.name, el.options[j].value);
                        }
                    }
                    continue;
                }
                params.append(el.name, el.value);
            }
            return params;
        }

        // Don't create a brand-new draft row out of a tab that was opened
        // and left idle - only start persisting once there's something to
        // lose. Once the note already exists (autosaveUrl has been swapped
        // to the edit-style URL, or the page loaded on note_edit), always
        // save - there's already a real row to keep in sync.
        function isWorthSaving(params) {
            if (autosaveUrl.indexOf("/add/autosave/") === -1) {
                return true;
            }
            var title = (params.get("title") || "").trim();
            var body = (params.get("body") || "").trim();
            return Boolean(title || body);
        }

        function doAutosave(useBeacon) {
            var params = buildParams();
            if (!isWorthSaving(params)) {
                return;
            }
            var snapshot = params.toString();
            if (!useBeacon && snapshot === lastSnapshot) {
                return; // nothing changed since the last successful save
            }

            if (useBeacon) {
                // sendBeacon can't set custom headers, so the CSRF token
                // has to travel in the body instead - Django's CSRF
                // middleware accepts it there too.
                if (!navigator.sendBeacon) {
                    return;
                }
                var beaconParams = new URLSearchParams(params);
                beaconParams.append("csrfmiddlewaretoken", getCsrfToken());
                navigator.sendBeacon(autosaveUrl, beaconParams);
                return;
            }

            if (saving) {
                return;
            }
            saving = true;
            setStatus("Сохранение…");

            fetch(autosaveUrl, {
                method: "POST",
                headers: {
                    "X-CSRFToken": getCsrfToken(),
                    "X-Requested-With": "XMLHttpRequest",
                },
                body: params,
            })
                .then(function (response) {
                    return response.json().then(function (data) {
                        return { ok: response.ok, data: data };
                    });
                })
                .then(function (result) {
                    if (!result.ok || !result.data.ok) {
                        setStatus("Не удалось сохранить черновик");
                        return;
                    }
                    lastSnapshot = snapshot;
                    autosaveUrl = result.data.autosave_url;
                    if (result.data.edit_url && window.location.pathname !== result.data.edit_url) {
                        window.history.replaceState(null, "", result.data.edit_url);
                    }
                    setStatus("Черновик сохранён в " + formatTime(result.data.saved_at));
                })
                .catch(function () {
                    setStatus("Не удалось сохранить черновик");
                })
                .finally(function () {
                    saving = false;
                });
        }

        form.addEventListener("input", handleFieldEvent);
        form.addEventListener("change", handleFieldEvent);

        function handleFieldEvent(event) {
            var target = event.target;
            if (!target || target.type === "file" || target.name === "remove_attachments") {
                return;
            }
            window.clearTimeout(debounceTimer);
            debounceTimer = window.setTimeout(function () {
                doAutosave(false);
            }, DEBOUNCE_MS);
        }

        // The interval is what actually guarantees coverage: CKEditor5
        // syncs its content into the body textarea's .value programmatically
        // (see django_ckeditor_5's app.js), which never fires a native
        // input/change DOM event, so typing in the rich-text editor would
        // otherwise never trigger the debounce above.
        window.setInterval(function () {
            doAutosave(false);
        }, POLL_MS);

        document.addEventListener("visibilitychange", function () {
            if (document.visibilityState === "hidden") {
                doAutosave(true);
            }
        });
        window.addEventListener("pagehide", function () {
            doAutosave(true);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
