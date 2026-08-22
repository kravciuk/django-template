/**
 * Progressive-enhancement tag input for NoteForm.tags.
 *
 * The original taggit-rendered "#id_tags" text input (comma-separated
 * string) is kept in the DOM as the actual submitted field - this script
 * only builds a chips + suggestions UI on top of it and keeps its value in
 * sync. If this script fails to run at all, the plain original input is
 * simply left visible and works exactly as it always has.
 */
(function () {
    "use strict";

    // Captured at parse time, while document.currentScript is still valid
    // (works for a statically-included <script defer> tag).
    var SUGGEST_URL = document.currentScript ? document.currentScript.dataset.suggestUrl : null;
    var DEBOUNCE_MS = 200;

    function init() {
        var original = document.getElementById("id_tags");
        if (!original || !SUGGEST_URL) {
            return;
        }

        var tags = splitTags(original.value);
        var debounceTimer = null;

        var wrap = document.createElement("div");
        wrap.className = "tag-input";

        var chipRow = document.createElement("div");
        chipRow.className = "tag-chips";

        var textInput = document.createElement("input");
        textInput.type = "text";
        textInput.className = "tag-text-input";
        textInput.setAttribute("autocomplete", "off");
        textInput.setAttribute("placeholder", "Добавить тег…");

        var suggestions = document.createElement("ul");
        suggestions.className = "tag-suggestions";
        suggestions.hidden = true;

        wrap.appendChild(chipRow);
        wrap.appendChild(textInput);
        wrap.appendChild(suggestions);

        original.insertAdjacentElement("afterend", wrap);
        original.style.display = "none";

        function syncHiddenInput() {
            original.value = tags.join(", ");
        }

        function renderChips() {
            chipRow.textContent = "";
            tags.forEach(function (tag, index) {
                var chip = document.createElement("span");
                chip.className = "tag-chip";

                var label = document.createElement("span");
                label.textContent = tag;
                chip.appendChild(label);

                var remove = document.createElement("button");
                remove.type = "button";
                remove.className = "tag-chip-remove";
                remove.setAttribute("aria-label", "Удалить тег " + tag);
                remove.textContent = "×";
                remove.addEventListener("click", function () {
                    tags.splice(index, 1);
                    renderChips();
                    syncHiddenInput();
                });
                chip.appendChild(remove);

                chipRow.appendChild(chip);
            });
        }

        function addTag(rawValue) {
            var value = rawValue.trim();
            if (!value) {
                return;
            }
            var exists = tags.some(function (tag) {
                return tag.toLowerCase() === value.toLowerCase();
            });
            if (!exists) {
                tags.push(value);
                renderChips();
                syncHiddenInput();
            }
            textInput.value = "";
            hideSuggestions();
        }

        function hideSuggestions() {
            suggestions.hidden = true;
            suggestions.textContent = "";
        }

        function renderSuggestions(names) {
            var remaining = names.filter(function (name) {
                return !tags.some(function (tag) {
                    return tag.toLowerCase() === name.toLowerCase();
                });
            });
            if (!remaining.length) {
                hideSuggestions();
                return;
            }
            suggestions.textContent = "";
            remaining.forEach(function (name) {
                var item = document.createElement("li");
                item.textContent = name;
                // mousedown (not click) fires before the text input's blur,
                // so the suggestion is still there to be picked.
                item.addEventListener("mousedown", function (event) {
                    event.preventDefault();
                    addTag(name);
                    textInput.focus();
                });
                suggestions.appendChild(item);
            });
            suggestions.hidden = false;
        }

        function fetchSuggestions(query) {
            fetch(SUGGEST_URL + "?q=" + encodeURIComponent(query), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            })
                .then(function (response) {
                    return response.ok ? response.json() : { results: [] };
                })
                .then(function (data) {
                    renderSuggestions(data.results || []);
                })
                .catch(function () {
                    hideSuggestions();
                });
        }

        textInput.addEventListener("input", function () {
            var query = textInput.value.trim();
            window.clearTimeout(debounceTimer);
            if (!query) {
                hideSuggestions();
                return;
            }
            debounceTimer = window.setTimeout(function () {
                fetchSuggestions(query);
            }, DEBOUNCE_MS);
        });

        textInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addTag(textInput.value);
            } else if (event.key === "Backspace" && !textInput.value && tags.length) {
                tags.pop();
                renderChips();
                syncHiddenInput();
            } else if (event.key === "Escape") {
                hideSuggestions();
            }
        });

        textInput.addEventListener("blur", function () {
            // Delay so a suggestion's mousedown handler still runs first.
            window.setTimeout(hideSuggestions, 150);
        });

        renderChips();
        syncHiddenInput();
    }

    function splitTags(value) {
        return (value || "")
            .split(",")
            .map(function (tag) {
                return tag.trim();
            })
            .filter(Boolean);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
