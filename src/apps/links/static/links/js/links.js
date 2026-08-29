/**
 * /links/ dashboard: add/rename/delete groups, add/delete links - all
 * through apps.links's REST API, no page reload (see apps/links/api.py and
 * templates/links/home.html).
 *
 * Follows the project's existing conventions: CSRF token read from the
 * page's rendered {% csrf_token %} input (note_autosave.js), endpoint URLs
 * injected via data-* attributes on this <script> tag (tag_autocomplete.js),
 * DOM built from string-templated innerHTML (weather-widget.js).
 */
(function () {
    "use strict";

    var GROUPS_URL = document.currentScript ? document.currentScript.dataset.groupsUrl : null;
    var LINKS_URL = document.currentScript ? document.currentScript.dataset.linksUrl : null;

    function esc(value) {
        return String(value).replace(/[&<>"]/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
        });
    }

    function getCsrfToken() {
        var input = document.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function domainOf(url) {
        try {
            return new URL(url).host;
        } catch (error) {
            return url;
        }
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

    function init() {
        var groupsContainer = document.getElementById("links-groups");
        if (!groupsContainer || !GROUPS_URL || !LINKS_URL) {
            return;
        }

        var modals = {
            addGroup: document.getElementById("lp-modal-add-group"),
            renameGroup: document.getElementById("lp-modal-rename-group"),
            addLink: document.getElementById("lp-modal-add-link"),
            editLink: document.getElementById("lp-modal-edit-link"),
        };

        function openModal(modal) {
            var errorEl = modal.querySelector("[data-error]");
            if (errorEl) {
                errorEl.style.display = "none";
                errorEl.textContent = "";
            }
            modal.classList.add("is-open");
        }

        function closeModal(modal) {
            modal.classList.remove("is-open");
        }

        function showError(modal, message) {
            var errorEl = modal.querySelector("[data-error]");
            if (errorEl) {
                errorEl.textContent = message;
                errorEl.style.display = "block";
            }
        }

        document.querySelectorAll("[data-modal]").forEach(function (overlay) {
            overlay.addEventListener("click", function (event) {
                if (event.target === overlay) {
                    closeModal(overlay);
                }
            });
        });
        document.querySelectorAll("[data-action=close-modal]").forEach(function (button) {
            button.addEventListener("click", function () {
                closeModal(button.closest(".lp-modal-overlay"));
            });
        });

        // Any open group "..." dropdown closes on an outside click.
        document.addEventListener("click", function (event) {
            document.querySelectorAll(".link-group-menu.is-open").forEach(function (menu) {
                if (!menu.contains(event.target)) {
                    menu.classList.remove("is-open");
                }
            });
        });

        function iconHTML(link) {
            return link.favicon
                ? '<img src="' + esc(link.favicon) + '" alt="">'
                : '<span aria-hidden="true">🔗</span>';
        }

        function linkCardHTML(link) {
            return (
                '<div class="link-card" data-link-id="' + link.id + '">' +
                '<div class="link-card-actions">' +
                '<button type="button" class="link-card-edit" data-action="edit-link" aria-label="Edit link">✎</button>' +
                '<button type="button" class="link-card-remove" data-action="delete-link" aria-label="Remove link">&times;</button>' +
                "</div>" +
                '<a class="link-card-body" href="' + esc(link.url) + '" target="_blank" rel="noopener noreferrer">' +
                '<span class="link-card-icon">' + iconHTML(link) + "</span>" +
                '<span class="link-card-text">' +
                '<span class="link-card-title">' + esc(link.title) + "</span>" +
                '<span class="link-card-url">' + esc(domainOf(link.url)) + "</span>" +
                "</span></a></div>"
            );
        }

        function updateLinkCard(card, link) {
            card.querySelector(".link-card-body").setAttribute("href", link.url);
            card.querySelector(".link-card-title").textContent = link.title;
            card.querySelector(".link-card-url").textContent = domainOf(link.url);
            card.querySelector(".link-card-icon").innerHTML = iconHTML(link);
        }

        function groupHTML(group) {
            return (
                '<div class="link-group" data-group-id="' + group.id + '">' +
                '<div class="link-group-header">' +
                '<h2 class="link-group-title">' + esc(group.title) + "</h2>" +
                '<div class="link-group-menu">' +
                '<button type="button" class="link-group-menu-toggle" data-action="toggle-menu" aria-label="Group menu">⋯</button>' +
                '<div class="link-group-menu-dropdown">' +
                '<button type="button" data-action="rename-group">Rename</button>' +
                '<button type="button" class="link-group-delete" data-action="delete-group">Delete</button>' +
                "</div></div></div>" +
                '<div class="link-grid" style="--cards-per-row: ' + group.cards_per_row + ';"></div>' +
                '<button type="button" class="link-card-add" data-action="add-link">+ Add</button>' +
                "</div>"
            );
        }

        // --- Group menu toggle -------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            var toggle = event.target.closest("[data-action=toggle-menu]");
            if (toggle) {
                toggle.closest(".link-group-menu").classList.toggle("is-open");
            }
        });

        // --- Add group -----------------------------------------------------------
        // A plain listener on the button itself, not delegated via
        // groupsContainer - the button is deliberately a sibling of
        // #links-groups, not a child of it (see the CSS comment on
        // .link-group-add), so a click on it never bubbles through
        // groupsContainer at all.
        var addGroupButton = document.querySelector("[data-action=add-group]");
        addGroupButton.addEventListener("click", function () {
            var form = modals.addGroup.querySelector("form");
            form.reset();
            openModal(modals.addGroup);
        });

        modals.addGroup.querySelector("form").addEventListener("submit", function (event) {
            event.preventDefault();
            var form = event.target;
            apiRequest(GROUPS_URL, "POST", {
                title: form.title.value,
                cards_per_row: Number(form.cards_per_row.value),
            }).then(function (result) {
                if (!result.ok) {
                    showError(modals.addGroup, firstErrorMessage(result.data) || "Could not add the group.");
                    return;
                }
                groupsContainer.insertAdjacentHTML("beforeend", groupHTML(result.data));
                closeModal(modals.addGroup);
            });
        });

        // --- Rename group ----------------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            if (event.target.closest("[data-action=rename-group]")) {
                var group = event.target.closest(".link-group");
                var form = modals.renameGroup.querySelector("form");
                form.group_id.value = group.dataset.groupId;
                form.title.value = group.querySelector(".link-group-title").textContent;
                form.cards_per_row.value = group.querySelector(".link-grid").style.getPropertyValue("--cards-per-row").trim();
                openModal(modals.renameGroup);
            }
        });

        modals.renameGroup.querySelector("form").addEventListener("submit", function (event) {
            event.preventDefault();
            var form = event.target;
            var groupId = form.group_id.value;
            apiRequest(GROUPS_URL + groupId + "/", "PATCH", {
                title: form.title.value,
                cards_per_row: Number(form.cards_per_row.value),
            }).then(function (result) {
                if (!result.ok) {
                    showError(modals.renameGroup, firstErrorMessage(result.data) || "Could not rename the group.");
                    return;
                }
                var group = groupsContainer.querySelector('.link-group[data-group-id="' + groupId + '"]');
                group.querySelector(".link-group-title").textContent = result.data.title;
                group.querySelector(".link-grid").style.setProperty("--cards-per-row", result.data.cards_per_row);
                closeModal(modals.renameGroup);
            });
        });

        // --- Delete group ------------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            if (event.target.closest("[data-action=delete-group]")) {
                var group = event.target.closest(".link-group");
                if (!window.confirm("Delete this group and all its links?")) {
                    return;
                }
                apiRequest(GROUPS_URL + group.dataset.groupId + "/", "DELETE").then(function (result) {
                    if (result.ok) {
                        group.remove();
                    }
                });
            }
        });

        // --- Add link ------------------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            if (event.target.closest("[data-action=add-link]")) {
                var group = event.target.closest(".link-group");
                var form = modals.addLink.querySelector("form");
                form.reset();
                form.group_id.value = group.dataset.groupId;
                openModal(modals.addLink);
            }
        });

        modals.addLink.querySelector("form").addEventListener("submit", function (event) {
            event.preventDefault();
            var form = event.target;
            var groupId = form.group_id.value;
            var submitButton = form.querySelector('button[type="submit"]');
            submitButton.disabled = true;
            apiRequest(LINKS_URL, "POST", {
                title: form.title.value,
                url: form.url.value,
                group: Number(groupId),
            }).then(function (result) {
                submitButton.disabled = false;
                if (!result.ok) {
                    showError(modals.addLink, firstErrorMessage(result.data) || "Could not add the link.");
                    return;
                }
                var group = groupsContainer.querySelector('.link-group[data-group-id="' + groupId + '"]');
                group.querySelector(".link-grid").insertAdjacentHTML("beforeend", linkCardHTML(result.data));
                closeModal(modals.addLink);
            });
        });

        // --- Edit link -------------------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            if (event.target.closest("[data-action=edit-link]")) {
                var card = event.target.closest(".link-card");
                var form = modals.editLink.querySelector("form");
                form.link_id.value = card.dataset.linkId;
                form.title.value = card.querySelector(".link-card-title").textContent;
                form.url.value = card.querySelector(".link-card-body").getAttribute("href");
                openModal(modals.editLink);
            }
        });

        modals.editLink.querySelector("form").addEventListener("submit", function (event) {
            event.preventDefault();
            var form = event.target;
            var linkId = form.link_id.value;
            var submitButton = form.querySelector('button[type="submit"]');
            submitButton.disabled = true;
            apiRequest(LINKS_URL + linkId + "/", "PATCH", {
                title: form.title.value,
                url: form.url.value,
            }).then(function (result) {
                submitButton.disabled = false;
                if (!result.ok) {
                    showError(modals.editLink, firstErrorMessage(result.data) || "Could not save the link.");
                    return;
                }
                var card = groupsContainer.querySelector('.link-card[data-link-id="' + linkId + '"]');
                updateLinkCard(card, result.data);
                closeModal(modals.editLink);
            });
        });

        // --- Delete link ---------------------------------------------------------
        groupsContainer.addEventListener("click", function (event) {
            var button = event.target.closest("[data-action=delete-link]");
            if (!button) {
                return;
            }
            var card = button.closest(".link-card");
            apiRequest(LINKS_URL + card.dataset.linkId + "/", "DELETE").then(function (result) {
                if (result.ok) {
                    card.remove();
                }
            });
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
