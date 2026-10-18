(() => {
    "use strict";

    const STORAGE_KEY = "kush_bush_selected_guild";

    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[c]));

    function guildId() {
        if (window.GUILD_ID) return String(window.GUILD_ID);
        const logger = document.querySelector(".logger-page[data-guild-id]");
        if (logger?.dataset.guildId) return String(logger.dataset.guildId);
        const match = location.pathname.match(/^\/servers\/(\d+)/);
        return match ? match[1] : null;
    }

    function initials(name) {
        const parts = String(name || "Server").trim().split(/\s+/).filter(Boolean);
        return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0]?.slice(0, 2) || "??").toUpperCase();
    }

    function injectStyle() {
        if (document.getElementById("kb-server-context-style")) return;
        const style = document.createElement("style");
        style.id = "kb-server-context-style";
        style.textContent = `
            .kb-server-context{position:fixed;top:12px;right:14px;z-index:1800;display:flex;align-items:center;gap:9px;padding:7px 11px 7px 7px;border:1px solid rgba(255,255,255,.12);border-radius:999px;background:rgba(17,18,22,.92);backdrop-filter:blur(12px);box-shadow:0 8px 28px rgba(0,0,0,.28);color:#fff;text-decoration:none;max-width:min(310px,calc(100vw - 28px));font:600 12px/1.1 system-ui,sans-serif}
            .kb-server-context:hover{border-color:rgba(88,101,242,.7);color:#fff}
            .kb-server-context img,.kb-server-context-fallback{width:30px;height:30px;border-radius:50%;object-fit:cover;flex:0 0 30px;background:#2b2d31;display:grid;place-items:center;font-weight:800;font-size:10px}
            .kb-server-context-copy{min-width:0;display:flex;flex-direction:column;gap:2px}.kb-server-context-label{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:rgba(255,255,255,.48)}.kb-server-context-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        `;
        document.head.appendChild(style);
    }

    function getOrCreate() {
        let el = document.getElementById("kb-server-context");
        if (el) return el;
        el = document.createElement("a");
        el.id = "kb-server-context";
        el.className = "kb-server-context";
        el.href = "/servers";
        el.innerHTML = `<span class="kb-server-context-fallback">?</span><span class="kb-server-context-copy"><span class="kb-server-context-label">Current server</span><span class="kb-server-context-name">Loading…</span></span>`;
        document.body.appendChild(el);
        return el;
    }

    async function load() {
        const id = guildId();
        if (!id) return;
        try { localStorage.setItem(STORAGE_KEY, id); } catch (_) {}
        injectStyle();
        const el = getOrCreate();
        el.href = `/servers/${encodeURIComponent(id)}/dashboard`;
        const response = await fetch(`/api/servers/${encodeURIComponent(id)}/overview`, { cache: "no-store", credentials: "same-origin" });
        const result = await response.json();
        if (!response.ok || !result.success) throw new Error(result.error || `HTTP ${response.status}`);
        const server = result.server || {};
        const name = server.name || "Unknown Server";
        const copy = el.querySelector(".kb-server-context-name");
        if (copy) copy.textContent = name;
        const old = el.querySelector("img,.kb-server-context-fallback");
        if (old) old.remove();
        if (server.icon) {
            const img = document.createElement("img");
            img.src = server.icon;
            img.alt = name;
            img.referrerPolicy = "no-referrer";
            img.onerror = () => { img.remove(); const f=document.createElement("span"); f.className="kb-server-context-fallback"; f.textContent=initials(name); el.prepend(f); };
            el.prepend(img);
        } else {
            const f=document.createElement("span"); f.className="kb-server-context-fallback"; f.textContent=initials(name); el.prepend(f);
        }
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
