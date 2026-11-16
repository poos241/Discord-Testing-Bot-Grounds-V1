(() => {
    "use strict";

    const STORAGE_KEY = "kush_bush_selected_guild";

    function guildId() {
        if (window.GUILD_ID) return String(window.GUILD_ID);
        const logger = document.querySelector(".logger-page[data-guild-id]");
        if (logger?.dataset.guildId) return String(logger.dataset.guildId);
        const match = location.pathname.match(/^\/servers\/(\d+)/);
        return match ? match[1] : null;
    }

    // The navbar in base.html already shows the current-server pill
    // (#navbar-server-pill). An earlier version of this file injected
    // a second, position:fixed pill (#kb-server-context) that floated
    // over the logged-in user area — removed 2026-11-15. This load()
    // now only records the selected guild for other pages to reuse.
    function load() {
        const id = guildId();
        if (!id) return;
        try { localStorage.setItem(STORAGE_KEY, id); } catch (_) {}
    }

    async function loadBotAvatar() {
        const img = document.getElementById("bot-avatar");
        const fallback = document.getElementById("bot-avatar-fallback");
        if (!img) return;
        try {
            const r = await fetch("/api/status", {cache:"no-store", credentials:"same-origin"});
            const d = await r.json();
            const src = d.bot_avatar || d.bot?.avatar;
            if (!src) return;
            img.onload = () => { img.style.display="block"; if(fallback) fallback.style.display="none"; };
            img.onerror = () => { img.style.display="none"; if(fallback) fallback.style.display="flex"; };
            img.src = src;
        } catch (_) {}
    }

    document.addEventListener("DOMContentLoaded", () => { load(); loadBotAvatar(); });
})();
