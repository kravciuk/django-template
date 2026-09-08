/**
 * Notification bell in the site header (see templates/base.html): an
 * unread-count badge + dropdown of recent notifications, updated live over
 * the apps.notifications WebSocket (see apps/notifications/consumers.py) and
 * backed by the REST API (apps/notifications/api.py) for the initial state.
 *
 * Progressive enhancement, same spirit as note_autosave.js/links.js: if this
 * script fails or the socket can't connect, the rest of the page is
 * unaffected - there's just no bell.
 */
(function () {
    "use strict";

    var script = document.currentScript;
    var UNREAD_COUNT_URL = script ? script.dataset.unreadCountUrl : null;
    var LIST_URL = script ? script.dataset.listUrl : null;
    var MARK_ALL_READ_URL = script ? script.dataset.markAllReadUrl : null;

    var RECONNECT_DELAY_MS = 3000;
    var KIND_LABELS = { system: "Система", task: "Задача", message: "Сообщение" };
    // Small glyph per kind, shown in the colored .notifications-item-icon
    // circle (color itself comes from the kind-system/kind-task/kind-message
    // CSS classes in base.html) - plain characters, same minimal-dependency
    // spirit as the rest of this widget, no icon library.
    var KIND_GLYPHS = { system: "⚙", task: "✓", message: "✉" };

    var RELATIVE_TIME_FORMAT = (typeof Intl !== "undefined" && Intl.RelativeTimeFormat)
        ? new Intl.RelativeTimeFormat("ru", { numeric: "auto" })
        : null;
    var RELATIVE_TIME_UNITS = [
        ["year", 31536000], ["month", 2592000], ["week", 604800],
        ["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1],
    ];

    // "5 минут назад" / "вчера" style label from an ISO timestamp - built on
    // Intl.RelativeTimeFormat (native, no date library) with a plain
    // fallback for the rare browser without it.
    function formatRelativeTime(isoString) {
        var date = new Date(isoString);
        if (isNaN(date.getTime())) {
            return "";
        }
        var diffSeconds = (date.getTime() - Date.now()) / 1000;
        if (!RELATIVE_TIME_FORMAT) {
            return date.toLocaleString("ru");
        }
        for (var i = 0; i < RELATIVE_TIME_UNITS.length; i++) {
            var unit = RELATIVE_TIME_UNITS[i][0];
            var secondsInUnit = RELATIVE_TIME_UNITS[i][1];
            if (Math.abs(diffSeconds) >= secondsInUnit || unit === "second") {
                return RELATIVE_TIME_FORMAT.format(Math.round(diffSeconds / secondsInUnit), unit);
            }
        }
        return "";
    }

    function esc(value) {
        return String(value).replace(/[&<>"]/g, function (c) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
        });
    }

    function getCsrfToken() {
        // Read from the csrftoken cookie rather than scanning the page for a
        // {% csrf_token %} <input>, since the bell (and this script) is
        // present on every page, not just ones with a form - base.html's
        // hx-headers attribute already renders {{ csrf_token }}, which sets
        // the cookie on every page load.
        var match = document.cookie.match(/(?:^|; )csrftoken=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function apiRequest(url, method) {
        return fetch(url, {
            method: method,
            headers: {
                "X-CSRFToken": getCsrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
        });
    }

    function init() {
        var toggle = document.getElementById("notifications-toggle");
        var badge = document.getElementById("notifications-badge");
        var list = document.getElementById("notifications-list");
        var emptyItem = document.getElementById("notifications-empty");
        var markAllBtn = document.getElementById("notifications-mark-all-read");
        if (!toggle || !badge || !list || !UNREAD_COUNT_URL || !LIST_URL) {
            return;
        }

        var unreadCount = 0;
        var listLoaded = false;

        function setBadge(count) {
            unreadCount = Math.max(0, count);
            toggle.classList.toggle("has-unread", unreadCount > 0);
            if (unreadCount > 0) {
                badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
                badge.style.display = "";
            } else {
                badge.style.display = "none";
            }
        }

        function clearEmptyPlaceholder() {
            if (emptyItem) {
                emptyItem.remove();
                emptyItem = null;
            }
        }

        // Re-adds the "Нет уведомлений" placeholder once the list is
        // fully emptied out by deletions - clearEmptyPlaceholder() above
        // only ever removes it, it never comes back on its own.
        function showEmptyPlaceholderIfNeeded() {
            if (list.querySelector(".notifications-item")) {
                return;
            }
            if (emptyItem) {
                return;
            }
            emptyItem = document.createElement("li");
            emptyItem.className = "px-3 py-2 text-muted small";
            emptyItem.id = "notifications-empty";
            emptyItem.textContent = "Нет уведомлений";
            list.appendChild(emptyItem);
        }

        function renderItem(item) {
            var li = document.createElement("li");
            li.className = "notifications-item";
            li.dataset.id = item.id;

            var title = (item.payload && item.payload.title) || KIND_LABELS[item.kind] || item.kind;
            var body = (item.payload && item.payload.body) || "";
            var kindClass = "kind-" + (KIND_GLYPHS[item.kind] ? item.kind : "system");

            var icon = document.createElement("div");
            icon.className = "notifications-item-icon " + kindClass;
            icon.textContent = KIND_GLYPHS[item.kind] || KIND_GLYPHS.system;
            icon.setAttribute("aria-hidden", "true");

            var content = document.createElement("div");
            content.className = "notifications-item-content flex-grow-1";
            content.innerHTML =
                '<div class="notifications-item-title">' + esc(title) +
                (item.sender_display
                    ? ' <span class="notifications-item-sender">— ' + esc(item.sender_display) + "</span>"
                    : "") +
                "</div>" +
                (body ? '<div class="notifications-item-body">' + esc(body) + "</div>" : "") +
                '<div class="notifications-item-meta">' +
                    (item.is_read ? "" : '<span class="notifications-item-dot" title="Непрочитано"></span>') +
                    "<span>" + esc(formatRelativeTime(item.created_at)) + "</span>" +
                "</div>";

            if (!item.is_read) {
                content.style.cursor = "pointer";
                content.title = "Отметить прочитанным";
                content.addEventListener("click", function () {
                    apiRequest(LIST_URL + item.id + "/mark_read/", "POST").then(function (response) {
                        if (!response.ok) {
                            return;
                        }
                        item.is_read = true;
                        var dot = content.querySelector(".notifications-item-dot");
                        if (dot) {
                            dot.remove();
                        }
                        content.style.cursor = "";
                        content.removeAttribute("title");
                        setBadge(unreadCount - 1);
                    });
                });
            }

            // Dismiss ("stop showing") button - deletes the notification
            // outright via DELETE {LIST_URL}{id}/ (NotificationViewSet now
            // mixes in DestroyModelMixin, scoped to the logged-in user's own
            // notifications). stopPropagation keeps this from also
            // triggering the mark-as-read click handler on `content` above.
            // Plain text "x" with an explicit light color, styled in
            // base.html (.notifications-item-delete) - deliberately not
            // Bootstrap's .btn-close/.btn-close-white: that's an SVG
            // background-image behind a CSS filter, and in practice it
            // rendered as a barely-visible dark smudge against this
            // dropdown's dark background (inherited from the <nav
            // data-bs-theme="dark">) no matter which filter variant was
            // used. Same approach as the tag-remove button (see
            // .tag-chip-remove above) - a real glyph with a real color is
            // far more predictable than a themed icon filter.
            var deleteBtn = document.createElement("button");
            deleteBtn.type = "button";
            deleteBtn.className = "notifications-item-delete flex-shrink-0";
            deleteBtn.setAttribute("aria-label", "Удалить уведомление");
            deleteBtn.title = "Удалить уведомление";
            deleteBtn.textContent = "✕";
            deleteBtn.addEventListener("click", function (event) {
                event.stopPropagation();
                deleteBtn.disabled = true;
                apiRequest(LIST_URL + item.id + "/", "DELETE").then(function (response) {
                    if (!response.ok && response.status !== 404) {
                        deleteBtn.disabled = false;
                        return;
                    }
                    var wasUnread = !item.is_read;
                    li.remove();
                    if (wasUnread) {
                        setBadge(unreadCount - 1);
                    }
                    showEmptyPlaceholderIfNeeded();
                });
            });

            li.appendChild(icon);
            li.appendChild(content);
            li.appendChild(deleteBtn);
            return li;
        }

        function prependItem(item) {
            clearEmptyPlaceholder();
            list.insertBefore(renderItem(item), list.firstChild);
        }

        // Surfaces a failure directly in the dropdown, instead of leaving
        // "Нет уведомлений" up on a request that actually failed - there's
        // no devtools console on every device (e.g. mobile browsers), so
        // this is often the only way to see what went wrong.
        function showListError(message) {
            clearEmptyPlaceholder();
            var li = document.createElement("li");
            li.className = "px-3 py-2 text-danger small";
            li.textContent = message;
            list.appendChild(li);
        }

        function describeResponse(response) {
            return "HTTP " + response.status + (response.statusText ? " " + response.statusText : "");
        }

        function loadList() {
            if (listLoaded) {
                return;
            }
            listLoaded = true;
            apiRequest(LIST_URL, "GET")
                .then(function (response) {
                    if (!response.ok) {
                        showListError("Не удалось загрузить уведомления (" + describeResponse(response) + ")");
                        listLoaded = false;
                        return null;
                    }
                    return response.json();
                })
                .then(function (data) {
                    if (data === null) {
                        return;
                    }
                    var results = data.results || [];
                    if (results.length === 0) {
                        return;
                    }
                    clearEmptyPlaceholder();
                    results.forEach(function (item) {
                        list.appendChild(renderItem(item));
                    });
                })
                .catch(function (error) {
                    listLoaded = false;
                    showListError("Не удалось загрузить уведомления (" + error + ")");
                });
        }

        function loadUnreadCount() {
            apiRequest(UNREAD_COUNT_URL, "GET")
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(describeResponse(response));
                    }
                    return response.json();
                })
                .then(function (data) { setBadge(data.count || 0); })
                .catch(function (error) {
                    // No unread count available - show a distinct marker
                    // (rather than nothing) so a failure isn't
                    // indistinguishable from "zero unread".
                    badge.textContent = "!";
                    badge.title = "Не удалось загрузить счётчик уведомлений (" + error + ")";
                    badge.style.display = "";
                });
        }

        function connectWebSocket() {
            var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
            var ws = new WebSocket(protocol + "//" + window.location.host + "/ws/notifications/");

            ws.onmessage = function (event) {
                var item;
                try {
                    item = JSON.parse(event.data);
                } catch (error) {
                    return;
                }
                setBadge(unreadCount + 1);
                if (listLoaded) {
                    prependItem(item);
                }
            };

            ws.onclose = function (event) {
                // 4401 = apps.notifications.consumers.NotificationConsumer
                // rejected the connection as unauthenticated - retrying
                // won't help until the user logs back in.
                if (event.code === 4401) {
                    return;
                }
                setTimeout(connectWebSocket, RECONNECT_DELAY_MS);
            };

            ws.onerror = function () {
                ws.close();
            };
        }

        toggle.addEventListener("click", loadList);

        if (markAllBtn && MARK_ALL_READ_URL) {
            markAllBtn.addEventListener("click", function () {
                apiRequest(MARK_ALL_READ_URL, "POST").then(function (response) {
                    if (!response.ok) {
                        return;
                    }
                    setBadge(0);
                    var items = list.querySelectorAll(".notifications-item");
                    for (var i = 0; i < items.length; i++) {
                        var content = items[i].querySelector(".notifications-item-content");
                        if (content) {
                            content.style.cursor = "";
                            content.removeAttribute("title");
                            var dot = content.querySelector(".notifications-item-dot");
                            if (dot) {
                                dot.remove();
                            }
                        }
                    }
                });
            });
        }

        loadUnreadCount();
        connectWebSocket();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
