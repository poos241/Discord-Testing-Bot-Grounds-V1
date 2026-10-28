/* Member directory: tag cloud filtering + search, client-side render. */
(function () {
    var tagCloud = document.getElementById("directory-tag-cloud");
    var results = document.getElementById("directory-results");
    var countEl = document.getElementById("directory-count");
    var emptyEl = document.getElementById("directory-empty");
    var searchInput = document.getElementById("directory-search");
    var clearBtn = document.getElementById("directory-clear");
    if (!tagCloud || !results) return;

    var selected = new Set();
    var searchTimer = null;

    var params = new URLSearchParams(window.location.search);
    params.getAll("tag").forEach(function (t) {
        if (t) selected.add(t.toLowerCase());
    });
    if (params.get("search")) searchInput.value = params.get("search");

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function syncUrl() {
        var p = new URLSearchParams();
        selected.forEach(function (t) { p.append("tag", t); });
        if (searchInput.value.trim()) p.set("search", searchInput.value.trim());
        var qs = p.toString();
        var url = window.location.pathname + (qs ? "?" + qs : "");
        window.history.replaceState(null, "", url);
    }

    function renderTags(tags) {
        if (!tags.length) {
            tagCloud.innerHTML = "<span class=\"directory-loading\">No tags on public profiles yet.</span>";
            return;
        }
        tagCloud.innerHTML = "";
        tags.forEach(function (t) {
            var btn = document.createElement("button");
            btn.type = "button";
            btn.className = "directory-tag" + (selected.has(t.tag.toLowerCase()) ? " selected" : "");
            btn.textContent = t.tag + " (" + t.count + ")";
            btn.addEventListener("click", function () {
                var key = t.tag.toLowerCase();
                if (selected.has(key)) selected.delete(key);
                else selected.add(key);
                load();
            });
            tagCloud.appendChild(btn);
        });
    }

    function dmLabel(code) {
        if (code === "open") return "DMs open";
        if (code === "closed") return "DMs closed";
        if (code === "ask") return "Ask before DMing";
        return "";
    }

    function renderMembers(members, total, truncated) {
        countEl.textContent = total === 1
            ? "1 member"
            : total + " members" + (truncated ? " (showing first 200)" : "");
        emptyEl.style.display = members.length ? "none" : "";
        if (!members.length) {
            results.innerHTML = "";
            return;
        }
        results.innerHTML = members.map(function (m) {
            var tags = (m.tags || []).map(function (t) {
                return "<span class=\"directory-card-tag" +
                    (selected.has(t.toLowerCase()) ? " selected" : "") +
                    "\">" + esc(t) + "</span>";
            }).join("");
            var badges = (m.badges || []).map(function (b) {
                return "<span title=\"" + esc(b.name) + "\">" + esc(b.icon) + "</span>";
            }).join(" ");
            var socials = (m.socials || []).map(function (u) {
                return "<a href=\"" + esc(u) + "\" target=\"_blank\" rel=\"noopener\">" + esc(u) + "</a>";
            }).join("");
            var dm = dmLabel(m.dm_status);
            var local = "";
            if (m.location) local += esc(m.location);
            if (m.timezone) local += (local ? " - " : "") + esc(m.timezone);
            return "<article class=\"directory-card\">" +
                "<div class=\"directory-card-head\">" +
                (m.avatar_url ? "<img src=\"" + esc(m.avatar_url) + "\" alt=\"\">" : "") +
                "<div><div class=\"directory-card-name\"><a href=\"" + esc(m.profile_url) + "\">" +
                esc(m.display_name) + "</a></div>" +
                (m.pronouns ? "<div class=\"directory-card-pronouns\">" + esc(m.pronouns) + "</div>" : "") +
                "</div></div>" +
                (m.status ? "<p class=\"directory-card-status\">" + esc(m.status) + "</p>" : "") +
                (m.bio ? "<p class=\"directory-card-bio\">" + esc(m.bio) + "</p>" : "") +
                (tags ? "<div class=\"directory-card-tags\">" + tags + "</div>" : "") +
                "<p class=\"directory-card-stats\">Level " + esc(m.stats.level) +
                " - " + esc(m.stats.xp) + " XP - " + esc(m.stats.played) +
                " games - " + esc(m.stats.points) + " points</p>" +
                (badges ? "<div class=\"directory-card-badges\">" + badges + "</div>" : "") +
                (socials ? "<div class=\"directory-card-socials\">" + socials + "</div>" : "") +
                (local ? "<p class=\"directory-card-dm\">" + local + "</p>" : "") +
                (dm ? "<p class=\"directory-card-dm\">" + esc(dm) + "</p>" : "") +
                "</article>";
        }).join("");
    }

    function load() {
        syncUrl();
        var p = new URLSearchParams();
        selected.forEach(function (t) { p.append("tag", t); });
        if (searchInput.value.trim()) p.set("search", searchInput.value.trim());
        fetch("/api/directory?" + p.toString())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.success) {
                    results.innerHTML = "<p>Could not load the directory.</p>";
                    return;
                }
                renderTags(data.tags || []);
                renderMembers(data.members || [], data.total || 0, !!data.truncated);
            })
            .catch(function () {
                results.innerHTML = "<p>Could not load the directory.</p>";
            });
    }

    searchInput.addEventListener("input", function () {
        if (searchTimer) clearTimeout(searchTimer);
        searchTimer = setTimeout(load, 300);
    });
    clearBtn.addEventListener("click", function () {
        selected.clear();
        searchInput.value = "";
        load();
    });

    load();
})();
