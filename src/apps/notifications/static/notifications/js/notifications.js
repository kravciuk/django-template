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

        function renderItem(item) {
            var li = document.createElement("li");
            li.className = "px-3 py-2 border-bottom notifications-item" + (item.is_read ? "" : " fw-semibold");
            li.dataset.id = item.id;

            var title = (item.payload && item.payload.title) || KIND_LABELS[item.kind] || item.kind;
            var body = (item.payload && item.payload.body) || "";

            li.innerHTML =
                '<div class="small text-uppercase text-muted">' + esc(KIND_LABELS[item.kind] || item.kind) + "</div>" +
                '<div>' + esc(title) + "</div>" +
                (body ? '<div class="small text-muted">' + esc(body) + "</div>" : "");

            if (!item.is_read) {
                li.style.cursor = "pointer";
                li.title = "Отметить прочитанным";
                li.addEventListener("click", function () {
                    apiRequest(LIST_URL + item.id + "/mark_read/", "POST").then(function (response) {
                        if (!response.ok) {
                            return;
                        }
                        item.is_read = true;
                        li.classList.remove("fw-semibold");
                        li.style.cursor = "";
                        li.removeAttribute("title");
                        setBadge(unreadCount - 1);
                    });
                });
            }
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
                        items[i].classList.remove("fw-semibold");
                        items[i].style.cursor = "";
                        items[i].removeAttribute("title");
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
