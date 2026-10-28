/* Community activity feed: kind filter + pagination, client-side render. */
(function () {
    var list = document.getElementById("feed-list");
    var countEl = document.getElementById("feed-count");
    var emptyEl = document.getElementById("feed-empty");
    var prevBtn = document.getElementById("feed-prev");
    var nextBtn = document.getElementById("feed-next");
    var pageLabel = document.getElementById("feed-page-label");
    var refreshBtn = document.getElementById("feed-refresh");
    var filterBtns = document.querySelectorAll("#feed-filters .feed-filter");
    if (!list) return;

    var params = new URLSearchParams(window.location.search);
    var kind = params.get("kind") || "";
    var page = parseInt(params.get("page") || "1", 10);
    if (!page || page < 1) page = 1;

    filterBtns.forEach(function (btn) {
        if (btn.getAttribute("data-kind") === kind) {
            btn.classList.add("selected");
        } else {
            btn.classList.remove("selected");
        }
        btn.addEventListener("click", function () {
            kind = btn.getAttribute("data-kind") || "";
            page = 1;
            load();
        });
    });

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    /* Same wording as the profile page's activity list, so an
       entry reads identically in both places. */
    function activityText(a) {
        var d = a.detail || {};
        if (a.kind === "level_up") return "Reached level " + (d.level || "?");
        if (a.kind === "daily_claim") return "Claimed daily reward (" + (d.streak || 1) + "-day streak)";
        if (a.kind === "badge_award") return "Awarded the \"" + (d.badge || "?") + "\" badge";
        if (a.kind === "game_round") {
            var pts = d.majority ? "(+" + (d.points || 0) + " pts, with the majority)" : "(against the crowd)";
            return "Eat It or Yeet It: " + (d.food || "something") + " — voted " + (d.voted || "?") + ", verdict " + (d.verdict || "?") + " " + pts;
        }
        return a.kind;
    }

    function fmtTime(ts) {
        if (!ts) return "";
        try {
            return new Date(ts * 1000).toLocaleString();
        } catch (e) {
            return "";
        }
    }

    function syncUrl() {
        var p = new URLSearchParams();
        if (kind) p.set("kind", kind);
        if (page > 1) p.set("page", String(page));
        var qs = p.toString();
        var url = window.location.pathname + (qs ? "?" + qs : "");
        window.history.replaceState(null, "", url);
    }

    function render(data) {
        var entries = data.entries || [];
        countEl.textContent = entries.length
            ? "Page " + data.page + " — showing " + entries.length + " recent entries."
            : "";
        emptyEl.style.display = entries.length ? "none" : "";
        prevBtn.disabled = !data.has_prev;
        nextBtn.disabled = !data.has_next;
        pageLabel.textContent = "Page " + data.page;
        if (!entries.length) {
            list.innerHTML = "";
            return;
        }
        list.innerHTML = entries.map(function (e) {
            var avatar = e.avatar_url
                ? "<img src=\"" + esc(e.avatar_url) + "\" alt=\"\">"
                : "<span class=\"feed-avatar-fallback\">?</span>";
            return "<div class=\"feed-entry\">"
                + "<div class=\"feed-entry-head\">" + avatar
                + "<a href=\"" + esc(e.profile_url) + "\">" + esc(e.display_name) + "</a>"
                + "<span class=\"feed-entry-time\">" + esc(fmtTime(e.ts)) + "</span>"
                + "</div>"
                + "<div class=\"feed-entry-text\">" + esc(activityText(e)) + "</div>"
                + "</div>";
        }).join("");
    }

    function load() {
        syncUrl();
        var q = new URLSearchParams();
        if (kind) q.set("kind", kind);
        q.set("page", String(page));
        list.innerHTML = "<p class=\"feed-loading\">Loading activity...</p>";
        fetch("/api/feed?" + q.toString())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) {
                    list.innerHTML = "<p class=\"feed-loading\">Could not load the feed. Try refreshing.</p>";
                    return;
                }
                render(data);
            })
            .catch(function () {
                list.innerHTML = "<p class=\"feed-loading\">Could not load the feed. Try refreshing.</p>";
            });
    }

    prevBtn.addEventListener("click", function () {
        if (page > 1) { page -= 1; load(); }
    });
    nextBtn.addEventListener("click", function () {
        page += 1; load();
    });
    if (refreshBtn) refreshBtn.addEventListener("click", load);

    load();
})();
