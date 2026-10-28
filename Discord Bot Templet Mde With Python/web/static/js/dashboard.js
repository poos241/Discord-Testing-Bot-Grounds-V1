let currentGuildId =
    window.GUILD_ID
        ? String(window.GUILD_ID)
        : null;

let availableServers = [];

let dashboardRefreshTimer = null;

let activityRefreshTimer = null;

const REFRESH_INTERVAL = 15000;

const SERVER_STORAGE_KEY =
    "kush_bush_selected_guild";


/* =========================================================
   START
   ========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        setupNavigation();

        setupServerPicker();

        await loadServers();

        await loadStatus();

        await loadBotAvatar();

        

        if (currentGuildId) {

            await loadDashboard();

            await loadOverviewData();

            await loadServerAnalytics();

            startAutoRefresh();

        }

    }
);


/* =========================================================
   NAVIGATION
   ========================================================= */

function setupNavigation() {

    const links =
        document.querySelectorAll(
            "[data-dashboard-link]"
        );

    links.forEach(
        link => {

            link.addEventListener(
                "click",
                event => {

                    event.preventDefault();

                    const href =
                        link.getAttribute(
                            "href"
                        );

                    if (href) {

                        window.location.href =
                            href;

                    }

                }
            );

        }
    );

}


/* =========================================================
   SERVERS
   ========================================================= */




function getSavedGuildId() {

    try {

        return localStorage.getItem(
            SERVER_STORAGE_KEY
        );

    }

    catch (error) {

        console.warn(
            "Could not read saved server:",
            error
        );

        return null;

    }

}


function saveGuildId(
    guildId
) {

    if (!guildId) {

        return;

    }


    try {

        localStorage.setItem(
            SERVER_STORAGE_KEY,
            String(guildId)
        );

    }

    catch (error) {

        console.warn(
            "Could not save selected server:",
            error
        );

    }

}


function getServerById(
    guildId
) {

    return availableServers.find(
        server =>
            String(
                server.id ||
                server.guild_id
            ) ===
            String(
                guildId
            )
    );

}


function getServerIcon(
    server
) {

    if (
        server &&
        server.icon
    ) {

        return server.icon;

    }


    return null;

}


function createServerIcon(
    server,
    className = ""
) {

    const wrapper =
        document.createElement(
            "div"
        );


    wrapper.className =
        `server-picker-icon ${className}`;


    const icon =
        getServerIcon(
            server
        );


    if (icon) {

        const img =
            document.createElement(
                "img"
            );


        img.src =
            icon;


        img.alt =
            `${server.name || "Server"} icon`;


        img.loading =
            "lazy";


        img.onerror =
            () => {

                img.remove();

                wrapper.textContent =
                    getServerInitials(
                        server.name
                    );

            };


        wrapper.appendChild(
            img
        );

    }

    else {

        wrapper.textContent =
            getServerInitials(
                server.name
            );

    }


    return wrapper;

}


function getServerInitials(
    name
) {

    const value =
        String(
            name ||
            "Server"
        ).trim();


    if (!value) {

        return "??";

    }


    const parts =
        value.split(
            /\s+/
        );


    if (
        parts.length >= 2
    ) {

        return (
            parts[0][0] +
            parts[1][0]
        )
            .toUpperCase();

    }


    return value
        .substring(
            0,
            2
        )
        .toUpperCase();

}


function renderServerPicker(
    servers
) {

    const list =
        document.getElementById(
            "server-picker-list"
        );


    const count =
        document.getElementById(
            "server-picker-count"
        );


    if (!list) {

        return;

    }


    availableServers =
        Array.isArray(
            servers
        )
            ? servers
            : [];


    if (count) {

        count.textContent =
            availableServers.length;

    }


    list.innerHTML = "";


    if (!availableServers.length) {

        list.innerHTML = `

            <div class="server-picker-empty">

                <div class="server-picker-empty-icon">
                    !
                </div>

                <div>
                    No Discord servers found.
                </div>

            </div>

        `;

        return;

    }


    const savedGuildId =
        getSavedGuildId();


    let selectedServer =
        getServerById(
            savedGuildId
        );


    if (
        !selectedServer &&
        window.GUILD_ID
    ) {

        selectedServer =
            getServerById(
                window.GUILD_ID
            );

    }


    if (
        !selectedServer
    ) {

        selectedServer =
            availableServers[0];

    }


    if (selectedServer) {

        currentGuildId =
            String(
                selectedServer.id ||
                selectedServer.guild_id
            );


        saveGuildId(
            currentGuildId
        );

    }


    availableServers.forEach(
        server => {

            const guildId =
                String(
                    server.id ||
                    server.guild_id
                );


            const item =
                document.createElement(
                    "button"
                );


            item.type =
                "button";


            item.className =
                "server-picker-item";


            item.dataset.guildId =
                guildId;


            item.setAttribute(
                "role",
                "option"
            );


            item.setAttribute(
                "aria-selected",
                guildId ===
                    String(
                        currentGuildId
                    )
            );


            const icon =
                createServerIcon(
                    server
                );


            item.appendChild(
                icon
            );


            const info =
                document.createElement(
                    "div"
                );


            info.className =
                "server-picker-item-info";


            const name =
                document.createElement(
                    "span"
                );


            name.className =
                "server-picker-item-name";


            name.textContent =
                server.name ||
                "Unknown Server";


            const meta =
                document.createElement(
                    "span"
                );


            meta.className =
                "server-picker-item-meta";


            meta.textContent =
                `${Number(
                    server.member_count ||
                    0
                ).toLocaleString()} members`;


            info.appendChild(
                name
            );


            info.appendChild(
                meta
            );


            item.appendChild(
                info
            );


            if (
                guildId ===
                String(
                    currentGuildId
                )
            ) {

                item.classList.add(
                    "selected"
                );

            }


            item.addEventListener(
                "click",
                async () => {

                    await selectServer(
                        guildId
                    );

                }
            );


            list.appendChild(
                item
            );

        }
    );


    updateCurrentServerPicker();

    const searchInput =
        document.getElementById(
            "server-picker-search-input"
        );


    if (searchInput) {

        searchInput.value = "";

    }


    filterServerPicker(
        ""
    );

}


function updateCurrentServerPicker() {

    const server =
        getServerById(
            currentGuildId
        );


    const name =
        document.getElementById(
            "server-picker-current-name"
        );


    const iconContainer =
        document.getElementById(
            "server-picker-current-icon"
        );


    if (!server) {

        if (name) {

            name.textContent =
                "No server selected";

        }

        return;

    }


    if (name) {

        name.textContent =
            server.name ||
            "Unknown Server";

    }


    if (iconContainer) {

        iconContainer.innerHTML = "";


        const icon =
            createServerIcon(
                server
            );


        iconContainer.appendChild(
            icon
        );

    }


    updateServerPickerSelection();

}


function updateServerPickerSelection() {

    document
        .querySelectorAll(
            ".server-picker-item"
        )
        .forEach(
            item => {

                const selected =
                    String(
                        item.dataset.guildId
                    ) ===
                    String(
                        currentGuildId
                    );


                item.classList.toggle(
                    "selected",
                    selected
                );


                item.setAttribute(
                    "aria-selected",
                    selected
                );

            }
        );

}


async function selectServer(
    guildId
) {

    if (!guildId) {

        return;

    }


    currentGuildId =
        String(
            guildId
        );


    saveGuildId(
        currentGuildId
    );


    updateCurrentServerPicker();


    closeServerPicker();


    setupQuickActions();

    setupServerNavigation();


    await loadDashboard();

}


/* =========================================================
   SERVER PICKER SETUP
   ========================================================= */

function setupServerPicker() {

    const picker =
        document.getElementById(
            "server-picker"
        );

    const button =
        document.getElementById(
            "server-picker-button"
        );

    const menu =
        document.getElementById(
            "server-picker-menu"
        );

    const search =
        document.getElementById(
            "server-picker-search"
        );


    if (
        !picker ||
        !button ||
        !menu
    ) {

        console.warn(
            "[Server Picker] Required elements missing."
        );

        return;

    }


    /*
     * Open / close
     */

    button.addEventListener(
        "click",
        event => {

            event.preventDefault();

            event.stopPropagation();

            toggleServerPicker();

        }
    );


    /*
     * Search
     */

    if (search) {

        search.addEventListener(
            "input",
            () => {

                renderServerPicker(
                    search.value
                );

            }
        );


        search.addEventListener(
            "click",
            event => {

                event.stopPropagation();

            }
        );


        search.addEventListener(
            "keydown",
            event => {

                if (
                    event.key === "Escape"
                ) {

                    closeServerPicker();

                    button.focus();

                }

            }
        );

    }


    /*
     * Click outside
     */

    document.addEventListener(
        "click",
        event => {

            if (
                !picker.contains(
                    event.target
                )
            ) {

                closeServerPicker();

            }

        }
    );


    /*
     * Escape
     */

    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Escape"
            ) {

                closeServerPicker();

            }

        }
    );

}


/* =========================================================
   OPEN / CLOSE
   ========================================================= */

function toggleServerPicker() {

    const picker =
        document.getElementById(
            "server-picker"
        );


    if (!picker) {

        return;

    }


    const isOpen =
        picker.classList.contains(
            "open"
        );


    if (isOpen) {

        closeServerPicker();

    }

    else {

        openServerPicker();

    }

}


function openServerPicker() {

    const picker =
        document.getElementById(
            "server-picker"
        );

    const button =
        document.getElementById(
            "server-picker-button"
        );

    const search =
        document.getElementById(
            "server-picker-search"
        );


    if (!picker) {

        return;

    }


    picker.classList.add(
        "open"
    );


    if (button) {

        button.setAttribute(
            "aria-expanded",
            "true"
        );

    }


    /*
     * Refresh the visible list
     * every time the picker opens.
     */

    renderServerPicker(
        search
            ? search.value
            : ""
    );


    if (search) {

        setTimeout(
            () => {

                search.focus();

                search.select();

            },
            50
        );

    }

}

function closeServerPicker() {

    const picker =
        document.getElementById(
            "server-picker"
        );

    const button =
        document.getElementById(
            "server-picker-button"
        );


    if (!picker) {

        return;

    }


    picker.classList.remove(
        "open"
    );


    if (button) {

        button.setAttribute(
            "aria-expanded",
            "false"
        );

    }

}


/* =========================================================
   LOAD SERVERS
   ========================================================= */

async function loadServers() {

    const list =
        document.getElementById(
            "server-picker-list"
        );


    if (!list) {

        return;

    }


    list.innerHTML = `

        <div class="server-picker-loading">

            Loading servers...

        </div>

    `;


    try {

        const response =
            await fetch(
                "/api/servers",
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const result =
            await response.json();


        availableServers =
            result.servers || [];


        if (
            !availableServers.length
        ) {

            currentGuildId = null;

            updateServerPickerCurrent(
                null
            );


            list.innerHTML = `

                <div class="server-picker-empty">

                    No Discord servers found.

                </div>

            `;

            return;

        }


        /*
         * Priority:
         *
         * 1. URL server ID
         * 2. Previously selected server
         * 3. Existing global server ID
         * 4. First available server
         */

        const urlServer =
            new URLSearchParams(
                window.location.search
            ).get("server");


        const savedServer =
            localStorage.getItem(
                SERVER_STORAGE_KEY
            );


        const candidates = [

            urlServer,

            window.GUILD_ID,

            savedServer,

            currentGuildId

        ];


        let selectedServer = null;


        for (
            const candidate
            of candidates
        ) {

            if (!candidate) {

                continue;

            }


            selectedServer =
                availableServers.find(
                    server => {

                        const id =
                            server.id ||
                            server.guild_id;

                        return (
                            String(id) ===
                            String(candidate)
                        );

                    }
                );


            if (selectedServer) {

                break;

            }

        }


        if (!selectedServer) {

            selectedServer =
                availableServers[0];

        }


        currentGuildId =
            String(
                selectedServer.id ||
                selectedServer.guild_id
            );


        localStorage.setItem(
            SERVER_STORAGE_KEY,
            currentGuildId
        );


        updateServerPickerCurrent(
            selectedServer
        );


        renderServerPicker();


        setupQuickActions();

        setupServerNavigation();


    }

    catch (error) {

        console.error(
            "Failed to load servers:",
            error
        );


        list.innerHTML = `

            <div class="server-picker-error">

                Failed to load servers.

                <small>
                    ${escapeHtml(
                        error.message
                    )}
                </small>

            </div>

        `;

    }

}


/* =========================================================
   RENDER SERVER LIST
   ========================================================= */

function renderServerPicker(
    searchTerm = ""
) {

    const list =
        document.getElementById(
            "server-picker-list"
        );


    if (!list) {

        return;

    }


    const search =
        String(
            searchTerm || ""
        )
        .trim()
        .toLowerCase();


    const filtered =
        availableServers.filter(
            server => {

                const name =
                    String(
                        server.name || ""
                    )
                    .toLowerCase();


                const id =
                    String(
                        server.id ||
                        server.guild_id ||
                        ""
                    );


                return (
                    !search ||
                    name.includes(search) ||
                    id.includes(search)
                );

            }
        );


    if (!filtered.length) {

        list.innerHTML = `

            <div class="server-picker-empty">

                No servers match
                "<strong>${escapeHtml(
                    searchTerm
                )}</strong>"

            </div>

        `;

        return;

    }


    list.innerHTML = "";


    filtered.forEach(
        server => {

            const id =
                String(
                    server.id ||
                    server.guild_id
                );


            const name =
                server.name ||
                "Unknown Server";


            const item =
                document.createElement(
                    "button"
                );


            item.type =
                "button";


            item.className =
                "server-picker-item";


            if (
                String(
                    currentGuildId
                ) === id
            ) {

                item.classList.add(
                    "selected"
                );

            }


            const avatar =
                document.createElement(
                    "div"
                );


            avatar.className =
                "server-picker-item-avatar";


            if (server.icon) {

                avatar.innerHTML = `

                    <img
                        src="${escapeHtml(
                            server.icon
                        )}"
                        alt=""
                        loading="lazy"
                    >

                `;

            }

            else {

                avatar.textContent =
                    getServerInitials(
                        name
                    );

            }


            const info =
                document.createElement(
                    "div"
                );


            info.className =
                "server-picker-item-info";


            info.innerHTML = `

                <strong>
                    ${escapeHtml(
                        name
                    )}
                </strong>

                <small>
                    ${Number(
                        server.member_count || 0
                    ).toLocaleString()}
                    members
                </small>

            `;


            const check =
                document.createElement(
                    "span"
                );


            check.className =
                "server-picker-check";


            check.textContent =
                String(
                    currentGuildId
                ) === id
                    ? "✓"
                    : "";


            item.appendChild(
                avatar
            );

            item.appendChild(
                info
            );

            item.appendChild(
                check
            );


            item.addEventListener(
                "click",
                async event => {

                    event.preventDefault();

                    event.stopPropagation();

                    await selectServer(
                        server
                    );

                }
            );


            list.appendChild(
                item
            );

        }
    );

}


/* =========================================================
   SELECT SERVER
   ========================================================= */

async function selectServer(
    server
) {

    if (!server) {

        return;

    }


    const guildId =
        String(
            server.id ||
            server.guild_id ||
            ""
        );


    if (!guildId) {

        console.warn(
            "[Server Picker] Server has no guild ID.",
            server
        );

        return;

    }


    /*
     * Set current server
     */

    currentGuildId =
        guildId;


    /*
     * Persist it.
     */

    try {

        localStorage.setItem(
            SERVER_STORAGE_KEY,
            guildId
        );

    }

    catch (error) {

        console.warn(
            "[Server Picker] Could not save server:",
            error
        );

    }


    /*
     * Update UI
     */

    updateServerPickerCurrent(
        server
    );


    /*
     * Update list selection
     */

    document
        .querySelectorAll(
            ".server-picker-item"
        )
        .forEach(
            item => {

                const selected =
                    String(
                        item.dataset.guildId
                    ) ===
                    guildId;


                item.classList.toggle(
                    "selected",
                    selected
                );


                item.setAttribute(
                    "aria-selected",
                    selected
                );


                const check =
                    item.querySelector(
                        ".server-picker-check"
                    );


                if (check) {

                    check.textContent =
                        selected
                            ? "✓"
                            : "";

                }

            }
        );


    /*
     * Update URL without reload.
     */

    const url =
        new URL(
            window.location.href
        );


    url.searchParams.set(
        "server",
        guildId
    );


    window.history.replaceState(
        {},
        "",
        url
    );


    /*
     * Rebuild navigation links.
     */

    setupServerNavigation();


    /*
     * Close picker.
     */

    closeServerPicker();


    /*
     * Load the newly selected server.
     */

    await loadDashboard();

}


/* =========================================================
   UPDATE CURRENT SERVER
   ========================================================= */

function updateServerPickerCurrent(
    server
) {

    const name =
        document.getElementById(
            "server-picker-name"
        );

    const avatar =
        document.getElementById(
            "server-picker-avatar"
        );


    if (!server) {

        if (name) {

            name.textContent =
                "No server";

        }


        if (avatar) {

            avatar.innerHTML =
                "";

            avatar.textContent =
                "?";

        }

        return;

    }


    const serverName =
        server.name ||
        "Unknown Server";


    if (name) {

        name.textContent =
            serverName;

    }


    if (!avatar) {

        return;

    }


    avatar.innerHTML =
        "";


    if (server.icon) {

        const image =
            document.createElement(
                "img"
            );


        image.src =
            server.icon;


        image.alt =
            `${serverName} icon`;


        image.loading =
            "lazy";


        image.onerror =
            () => {

                avatar.innerHTML =
                    "";

                avatar.textContent =
                    getServerInitials(
                        serverName
                    );

            };


        avatar.appendChild(
            image
        );

    }

    else {

        avatar.textContent =
            getServerInitials(
                serverName
            );

    }

}


/* =========================================================
   SERVER INITIALS
   ========================================================= */

function getServerInitials(
    name
) {

    const words =
        String(
            name || "Server"
        )
        .trim()
        .split(
            /\s+/
        );


    if (
        words.length >= 2
    ) {

        return (
            words[0][0] +
            words[1][0]
        )
        .toUpperCase();

    }


    return String(
        name || "S"
    )
    .substring(
        0,
        2
    )
    .toUpperCase();

}


/* =========================================================
   BACKWARD COMPATIBILITY
   ========================================================= */

async function changeServer() {

    /*
     * Keep this function because
     * older dashboard code may still
     * call it.
     */

    const picker =
        document.getElementById(
            "server-picker"
        );


    if (picker) {

        toggleServerPicker();

    }

}

/* =========================================================
   STATUS
========================================================= */

async function loadStatus() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const data =
            await response.json();


        const online =
            data.online === true &&
            data.discord_ready === true;


        const status =
            document.getElementById(
                "bot-status"
            );


        const dot =
            document.getElementById(
                "status-dot"
            );


        if (status) {

            status.textContent =
                online
                    ? "Online"
                    : "Offline";

        }


        if (dot) {

            dot.classList.toggle(
                "online",
                online
            );

            dot.classList.toggle(
                "offline",
                !online
            );

        }


        const connectionText =
            document.getElementById(
                "connectionText"
            );


        if (connectionText) {

            connectionText.textContent =
                online
                    ? "Connected"
                    : "Disconnected";

        }


        const connectionDot =
            document.getElementById(
                "connectionDot"
            );


        if (connectionDot) {

            connectionDot.classList.toggle(
                "online",
                online
            );

            connectionDot.classList.toggle(
                "offline",
                !online
            );

        }


        /* =============================================
           BOT AVATAR
        ============================================= */

        const bot =
            data.bot;


        if (
            bot &&
            bot.avatar
        ) {

            const avatar =
                document.getElementById(
                    "bot-avatar"
                );


            const fallback =
                document.getElementById(
                    "bot-avatar-fallback"
                );


            if (avatar) {

                avatar.src =
                    bot.avatar;

                avatar.style.display =
                    "block";

            }


            if (fallback) {

                fallback.style.display =
                    "none";

            }

        }

    }

    catch (error) {

        console.error(
            "Status error:",
            error
        );

    }

}


/* =========================================================
   DASHBOARD
   ========================================================= */

async function loadDashboard() {

    if (!currentGuildId) {

        return;

    }


    showDashboardLoading();


    try {

        const response =
            await fetch(
                `/api/servers/${currentGuildId}/dashboard`,
                {
                    cache: "no-store"
                }
            );


        const result =
            await response.json();


        if (!response.ok) {

            throw new Error(
                result.error ||
                `HTTP ${response.status}`
            );

        }


        const dashboard =
            result.dashboard ||
            result;


        updateServerInfo(
            dashboard
        );

        updateEnhancedDashboard(
            dashboard
        );

        await Promise.all(
            [
                loadActivity(),
                loadActivitySummary(),
                loadServerHealth()
            ]
        );


        updateLastUpdated();


    }

    catch (error) {

        console.error(
            "Dashboard error:",
            error
        );

        showDashboardError(
            error.message
        );

    }

}


/* =========================================================
   DASHBOARD LOADING
   ========================================================= */

function showDashboardLoading() {

    const dashboard =
        document.getElementById(
            "dashboard"
        );

    if (!dashboard) {

        return;

    }

    dashboard.classList.add(
        "dashboard-loading"
    );

}


function showDashboardError(
    message
) {

    const dashboard =
        document.getElementById(
            "dashboard"
        );

    if (!dashboard) {

        return;

    }

    dashboard.innerHTML = `

        <div class="alert alert-danger shadow-sm">

            <div class="fw-bold mb-1">
                Unable to load server
            </div>

            <div>
                ${escapeHtml(
                    message ||
                    "Unknown error"
                )}
            </div>

            <button
                class="btn btn-sm btn-outline-danger mt-3"
                onclick="loadDashboard()"
            >
                Retry
            </button>

        </div>

    `;

}


/* =========================================================
   SERVER INFORMATION
   ========================================================= */

function updateServerInfo(dashboard) {
    const server = dashboard.server || dashboard.guild || dashboard || {};
    const members = dashboard.members || {};
    const channels = dashboard.channels || {};
    const roles = dashboard.roles || {};
    const events = dashboard.events || {};
    const name = server.name || "Unknown Server";

    setText("server-name", name);
    setText("server-subtitle", name);
    setText("server-id", server.id || currentGuildId || "--");
    setText("member-count", Number(members.count ?? server.member_count ?? 0).toLocaleString());
    setText("channel-count", Number(channels.count ?? server.channel_count ?? 0).toLocaleString());
    setText("role-count", Number(roles.count ?? server.role_count ?? 0).toLocaleString());
    setText("event-count", Number(events.count ?? events.total ?? 0).toLocaleString());
    setText("server-members", Number(members.count ?? server.member_count ?? 0).toLocaleString());
    setText("server-owner", server.owner_name || server.owner || server.owner_id || "--");
    setText("server-created", formatTimestamp(server.created_at));

    const avatar = document.getElementById("server-avatar");
    if (avatar) {
        avatar.innerHTML = "";
        if (server.icon) {
            const img = document.createElement("img");
            img.src = server.icon;
            img.alt = `${name} icon`;
            img.loading = "eager";
            img.referrerPolicy = "no-referrer";
            img.onerror = () => { img.remove(); avatar.textContent = getServerInitials(name); };
            avatar.appendChild(img);
        } else {
            avatar.textContent = getServerInitials(name);
        }
    }
}


/* =========================================================
   ACTIVITY
   ========================================================= */

async function loadActivity() {

    if (!currentGuildId) {

        return;

    }


    const container =
        document.getElementById(
            "activity-list"
        );


    if (!container) {

        return;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${currentGuildId}/activity?limit=50`,
                {
                    cache: "no-store"
                }
            );


        const result =
            await response.json();


        if (!response.ok) {

            throw new Error(
                result.error ||
                `HTTP ${response.status}`
            );

        }


        const events =
            result.events || [];


        renderActivity(
            events
        );

        const activeFilter =
            document.querySelector(
                ".activity-filter.active"
            );

        if (
            activeFilter &&
            activeFilter.dataset.filter !== "all"
        ) {

            filterActivity(
                activeFilter.dataset.filter
            );

        }


    }

    catch (error) {

        console.error(
            "Activity error:",
            error
        );


        container.innerHTML = `

            <div class="activity-empty">

                <div class="activity-empty-icon">
                    ⚠️
                </div>

                <div>
                    Failed to load activity.
                </div>

                <small>
                    ${escapeHtml(
                        error.message
                    )}
                </small>

            </div>

        `;

    }

}


/* =========================================================
   RENDER ACTIVITY
   ========================================================= */

function renderActivity(
    events
) {

    const container =
        document.getElementById(
            "activity-list"
        );


    if (!container) {

        return;

    }


    if (!events.length) {

        container.innerHTML = `

            <div class="activity-empty">

                <div class="activity-empty-icon">
                    ◌
                </div>

                <div>
                    No activity recorded yet.
                </div>

                <small>
                    Discord events will appear here.
                </small>

            </div>

        `;

        return;

    }


    container.innerHTML =
        events.map(
            event => {

                const type =
                    event.event_type ||
                    event.type ||
                    "unknown";


                const category =
                    event.category ||
                    "system";


                const cssClass =
                    eventClass(
                        type
                    );


                const data =
                    event.data ||
                    {};


                return `

                    <div
                        class="activity ${cssClass}"
                        data-event-type="${escapeHtml(type)}"
                    >

                        <div class="activity-icon">

                            ${eventIcon(
                                type
                            )}

                        </div>


                        <div class="activity-content">

                            <div class="activity-header">

                                <div>

                                    <span
                                        class="activity-type"
                                    >
                                        ${escapeHtml(
                                            formatEventType(
                                                type
                                            )
                                        )}
                                    </span>

                                    <span
                                        class="activity-category"
                                    >
                                        ${escapeHtml(
                                            category
                                        )}
                                    </span>

                                </div>


                                <div class="activity-time">

                                    ${formatTimestamp(
                                        event.timestamp
                                    )}

                                </div>

                            </div>


                            <div
                                class="activity-data"
                            >

                                ${renderEventPreview(
                                    data
                                )}

                            </div>

                        </div>

                    </div>

                `;

            }
        ).join("");

}


/* =========================================================
   EVENT SUMMARY
   ========================================================= */

async function loadActivitySummary() {

    if (!currentGuildId) {

        return;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${currentGuildId}/activity/summary`,
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            return;

        }


        const result =
            await response.json();


        const totalEvents =
            Number(
                result.total ??
                result.count ??
                0
            );


        setText(
            "event-count",
            totalEvents.toLocaleString()
        );


        const counts =
            result.event_types ||
            result.types ||
            result.breakdown ||
            {};


        renderActivitySummary(
            counts
        );

    }

    catch (error) {

        console.error(
            "Activity summary error:",
            error
        );

    }

}


/* =========================================================
   RENDER EVENT SUMMARY
   ========================================================= */

function renderActivitySummary(
    counts
) {

    const container =
        document.getElementById(
            "event-breakdown"
        );


    if (!container) {

        return;

    }


    const entries =
        Object.entries(
            counts
        );


    if (!entries.length) {

        container.innerHTML = `

            <div class="text-secondary">

                No event statistics yet.

            </div>

        `;

        return;

    }


    entries.sort(
        (
            a,
            b
        ) =>
            Number(b[1]) -
            Number(a[1])
    );


    container.innerHTML =
        entries
            .slice(
                0,
                12
            )
            .map(
                ([type, count]) => `

                    <div
                        class="event-stat"
                    >

                        <div>

                            <span
                                class="event-stat-icon"
                            >
                                ${eventIcon(
                                    type
                                )}
                            </span>

                            <span>
                                ${escapeHtml(
                                    formatEventType(
                                        type
                                    )
                                )}
                            </span>

                        </div>

                        <strong>
                            ${Number(
                                count
                            )}
                        </strong>

                    </div>

                `
            )
            .join("");

}


/* =========================================================
   EVENT CLASS
   ========================================================= */

function eventClass(
    eventType
) {

    const type =
        String(
            eventType ||
            ""
        ).toLowerCase();


    if (
        type.includes("delete") ||
        type.includes("remove") ||
        type.includes("ban") ||
        type.includes("kick")
    ) {

        return "event-danger";

    }


    if (
        type.includes("create") ||
        type.includes("add") ||
        type.includes("join") ||
        type.includes("start")
    ) {

        return "event-success";

    }


    if (
        type.includes("update") ||
        type.includes("edit") ||
        type.includes("change") ||
        type.includes("modify")
    ) {

        return "event-warning";

    }


    return "event-neutral";

}


/* =========================================================
   EVENT ICON
   ========================================================= */

function eventIcon(
    eventType
) {

    const type =
        String(
            eventType ||
            ""
        ).toLowerCase();


    if (
        type.includes("delete") ||
        type.includes("remove")
    ) {

        return "🗑️";

    }


    if (
        type.includes("ban") ||
        type.includes("kick")
    ) {

        return "🚫";

    }


    if (
        type.includes("join") ||
        type.includes("add")
    ) {

        return "➕";

    }


    if (
        type.includes("create")
    ) {

        return "✨";

    }


    if (
        type.includes("update") ||
        type.includes("edit") ||
        type.includes("change")
    ) {

        return "✏️";

    }


    if (
        type.includes("voice")
    ) {

        return "🎧";

    }


    if (
        type.includes("message")
    ) {

        return "💬";

    }


    if (
        type.includes("role")
    ) {

        return "🛡️";

    }


    if (
        type.includes("channel")
    ) {

        return "📁";

    }


    return "📌";

}


/* =========================================================
   EVENT FORMAT
   ========================================================= */

function formatEventType(
    value
) {

    return String(
        value ||
        "Unknown Event"
    )
        .replaceAll(
            "_",
            " "
        )
        .replace(
            /\b\w/g,
            letter =>
                letter.toUpperCase()
        );

}


/* =========================================================
   EVENT PREVIEW
   ========================================================= */

function renderEventPreview(
    data
) {

    if (!data) {

        return "";

    }


    if (
        typeof data ===
        "string"
    ) {

        return escapeHtml(
            data
        );

    }


    const preferred =
        [
            "description",
            "message",
            "content",
            "reason",
            "name",
            "username"
        ];


    for (
        const key
        of preferred
    ) {

        if (
            data[key] !==
            undefined &&
            data[key] !==
            null &&
            String(
                data[key]
            ).trim()
        ) {

            return escapeHtml(
                String(
                    data[key]
                )
            );

        }

    }


    return "";

}


/* =========================================================
   AUTO REFRESH
   ========================================================= */

function startAutoRefresh() {

    stopAutoRefresh();


    dashboardRefreshTimer =
        setInterval(
            async () => {

                await loadStatus();

            },
            REFRESH_INTERVAL
        );


    activityRefreshTimer =
        setInterval(
            async () => {

                if (currentGuildId) {

                    await loadActivity();

                    await loadActivitySummary();

                    updateLastUpdated();

                }

            },
            REFRESH_INTERVAL
        );

}


function stopAutoRefresh() {

    if (
        dashboardRefreshTimer
    ) {

        clearInterval(
            dashboardRefreshTimer
        );

        dashboardRefreshTimer =
            null;

    }


    if (
        activityRefreshTimer
    ) {

        clearInterval(
            activityRefreshTimer
        );

        activityRefreshTimer =
            null;

    }

}


/* =========================================================
   LAST UPDATED
   ========================================================= */

function updateLastUpdated() {

    const element =
        document.getElementById(
            "last-updated"
        );


    if (!element) {

        return;

    }


    element.textContent =
        `Updated ${new Date().toLocaleTimeString()}`;

}


/* =========================================================
   HELPERS
   ========================================================= */

/* Stat count-up (overnight polish): the dashboard's stat numbers
   (members, channels, roles, events, online/human/bot members, text/
   voice channels, categories) animate from 0 up to their first loaded
   value instead of popping in. Only the first real value per number
   animates; later auto-refreshes set the value directly, so the page
   never re-animates on every refresh cycle. Honors
   prefers-reduced-motion by setting the final value at once. */

const COUNT_UP_STAT_IDS =
    new Set(
        [
            "member-count",
            "channel-count",
            "role-count",
            "event-count",
            "online-members",
            "human-members",
            "bot-members",
            "text-channels",
            "voice-channels",
            "categories"
        ]
    );


const countedUpStats =
    new Set();


let countUpTokenCounter =
    0;


function animateCountUp(
    element,
    target
) {

    const token =
        String(
            ++countUpTokenCounter
        );

    element.dataset.countUpToken =
        token;


    if (
        window.matchMedia(
            "(prefers-reduced-motion: reduce)"
        ).matches
    ) {

        element.textContent =
            target.toLocaleString();

        return;

    }


    const durationMs =
        900;

    const startTime =
        performance.now();


    function frame(
        now
    ) {

        if (
            element.dataset.countUpToken !==
            token
        ) {

            return;

        }


        const progress =
            Math.min(
                (now - startTime) / durationMs,
                1
            );

        const eased =
            1 - Math.pow(
                1 - progress,
                3
            );

        element.textContent =
            Math.round(
                target * eased
            ).toLocaleString();

        if (progress < 1) {

            requestAnimationFrame(
                frame
            );

        }

    }


    requestAnimationFrame(
        frame
    );

}


function setText(
    id,
    value
) {

    const element =
        document.getElementById(
            id
        );


    if (element) {

        if (
            COUNT_UP_STAT_IDS.has(id) &&
            !countedUpStats.has(id)
        ) {

            const target =
                Number(
                    String(
                        value ?? ""
                    ).replace(
                        /[^0-9.-]/g,
                        ""
                    )
                );

            if (Number.isFinite(target)) {

                countedUpStats.add(id);

                animateCountUp(
                    element,
                    target
                );

                return;

            }

        }


        if (COUNT_UP_STAT_IDS.has(id)) {

            /* A later direct set cancels any count-up still running
               on this number, so a refresh can never fight the
               animation for the same element. */

            element.dataset.countUpToken =
                "stopped";

        }


        element.textContent =
            value ?? "--";

    }

}


function escapeHtml(
    value
) {

    return String(
        value ?? ""
    )
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );

}


function formatTimestamp(
    value
) {

    if (!value) {

        return "--";

    }


    const date =
        new Date(
            value
        );


    if (
        Number.isNaN(
            date.getTime()
        )
    ) {

        return escapeHtml(
            value
        );

    }


    return date.toLocaleString();

}


/* =========================================================
   MANUAL REFRESH
   ========================================================= */

async function refreshDashboard() {

    const button =
        document.getElementById(
            "refresh-button"
        );


    if (button) {

        button.classList.add(
            "refreshing"
        );

    }


    try {

        await loadStatus();

        await loadDashboard();

        await loadServerAnalytics();

        updateRefreshIndicator();

    }

    finally {

        if (button) {

            button.classList.remove(
                "refreshing"
            );

        }

    }

}


/* =========================================================
   SERVER ANALYTICS
========================================================= */

async function loadServerAnalytics() {

    if (!currentGuildId) {

        return;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(currentGuildId)}/analytics`,
                {
                    cache: "no-store",
                    credentials: "same-origin"
                }
            );


        const result =
            await response.json();


        if (!response.ok) {

            throw new Error(
                result.error ||
                `HTTP ${response.status}`
            );

        }


        updateServerAnalytics(
            result
        );


    }

    catch (error) {

        console.error(
            "[Dashboard] Analytics error:",
            error
        );

    }

}


/* =========================================================
   UPDATE ANALYTICS
========================================================= */

function updateServerAnalytics(
    data
) {

    const members =
        data.members ||
        {};

    const channels =
        data.channels ||
        {};

    const roles =
        data.roles ||
        {};

    const events =
        data.events ||
        {};


    const totalMembers =
        Math.max(
            Number(
                members.total ||
                0
            ),
            1
        );


    /* =====================================================
       MEMBERS
    ===================================================== */

    setText(
        "analytics-humans",
        Number(
            members.humans ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-bots",
        Number(
            members.bots ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-online",
        Number(
            members.online ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-idle",
        Number(
            members.idle ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-dnd",
        Number(
            members.dnd ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-offline",
        Number(
            members.offline ||
            0
        ).toLocaleString()
    );


    updateAnalyticsBar(
        "analytics-online-bar",
        members.online,
        totalMembers
    );


    updateAnalyticsBar(
        "analytics-idle-bar",
        members.idle,
        totalMembers
    );


    updateAnalyticsBar(
        "analytics-dnd-bar",
        members.dnd,
        totalMembers
    );


    updateAnalyticsBar(
        "analytics-offline-bar",
        members.offline,
        totalMembers
    );


    /* =====================================================
       CHANNELS
    ===================================================== */

    setText(
        "analytics-text",
        Number(
            channels.text ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-voice",
        Number(
            channels.voice ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-categories",
        Number(
            channels.categories ||
            0
        ).toLocaleString()
    );


    /* =====================================================
       ROLES
    ===================================================== */

    setText(
        "analytics-roles",
        Number(
            roles.total ||
            0
        ).toLocaleString()
    );


    /* =====================================================
       EVENTS
    ===================================================== */

    setText(
        "analytics-events-total",
        Number(
            events.total ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-events-hour",
        Number(
            events.last_hour ||
            0
        ).toLocaleString()
    );


    setText(
        "analytics-events-day",
        Number(
            events.last_24_hours ||
            0
        ).toLocaleString()
    );


    /* =====================================================
       TIMESTAMP
    ===================================================== */

    const updated =
        document.getElementById(
            "analytics-updated"
        );


    if (updated) {

        updated.textContent =
            new Date().toLocaleTimeString();

    }


    renderAnalyticsHourly(
        events.hourly ||
        []
    );


    renderTopAnalyticsEvents(
        events.top_event_types ||
        []
    );

}


/* =========================================================
   ANALYTICS BAR
========================================================= */

function updateAnalyticsBar(
    id,
    value,
    total
) {

    const element =
        document.getElementById(
            id
        );


    if (!element) {

        return;

    }


    const amount =
        Number(
            value ||
            0
        );


    const denominator =
        Math.max(
            Number(
                total ||
                1
            ),
            1
        );


    const percentage =
        Math.min(
            100,
            Math.max(
                0,
                (
                    amount /
                    denominator
                ) *
                100
            )
        );


    element.style.width =
        `${percentage}%`;

}


/* =========================================================
   HOURLY CHART
========================================================= */

function renderAnalyticsHourly(
    values
) {

    const container =
        document.getElementById(
            "analytics-hourly"
        );


    if (!container) {

        return;

    }


    const data =
        Array.isArray(
            values
        )
            ? values
            : [];


    if (!data.length) {

        container.innerHTML = `

            <div class="analytics-chart-empty">

                No activity data yet.

            </div>

        `;

        return;

    }


    const max =
        Math.max(
            ...data.map(
                value =>
                    Number(
                        value ||
                        0
                    )
            ),
            1
        );


    container.innerHTML =
        data.map(
            (
                value,
                index
            ) => {

                const amount =
                    Number(
                        value ||
                        0
                    );


                const height =
                    Math.max(
                        amount > 0
                            ? 8
                            : 2,
                        (
                            amount /
                            max
                        ) *
                        100
                    );


                return `

                    <div
                        class="analytics-hour"
                        title="${amount} event${amount === 1 ? "" : "s"}"
                    >

                        <div
                            class="analytics-hour-bar"
                            style="height:${height}%"
                        ></div>

                        <span>
                            ${index + 1}
                        </span>

                    </div>

                `;

            }
        ).join("");

}


/* =========================================================
   TOP EVENTS
========================================================= */

function renderTopAnalyticsEvents(
    events
) {

    const container =
        document.getElementById(
            "analytics-top-events-list"
        );


    if (!container) {

        return;

    }


    if (
        !Array.isArray(events) ||
        !events.length
    ) {

        container.innerHTML = `

            <div class="analytics-chart-empty">

                No events recorded yet.

            </div>

        `;

        return;

    }


    const maximum =
        Math.max(
            ...events.map(
                event =>
                    Number(
                        event.count ||
                        0
                    )
            ),
            1
        );


    container.innerHTML =
        events
            .slice(
                0,
                10
            )
            .map(
                event => {

                    const count =
                        Number(
                            event.count ||
                            0
                        );


                    const percentage =
                        (
                            count /
                            maximum
                        ) *
                        100;


                    return `

                        <div
                            class="analytics-event-row"
                        >

                            <div
                                class="analytics-event-name"
                            >

                                <span>
                                    ${eventIcon(
                                        event.event_type
                                    )}
                                </span>

                                <strong>
                                    ${escapeHtml(
                                        formatEventType(
                                            event.event_type
                                        )
                                    )}
                                </strong>

                            </div>


                            <div
                                class="analytics-event-progress"
                            >

                                <div
                                    class="analytics-event-progress-fill"
                                    style="width:${percentage}%"
                                ></div>

                            </div>


                            <span
                                class="analytics-event-count"
                            >
                                ${count.toLocaleString()}
                            </span>

                        </div>

                    `;

                }
            )
            .join("");

}


/* =========================================================
   EXPOSE GLOBAL FUNCTIONS
   ========================================================= */

window.loadDashboard =
    loadDashboard;

window.loadActivity =
    loadActivity;

window.loadActivitySummary =
    loadActivitySummary;

window.changeServer =
    changeServer;

window.refreshDashboard =
    refreshDashboard;

window.eventClass =
    eventClass;
    
window.loadServerHealth =
    loadServerHealth;

/* =========================================================
   QUICK ACTIONS
========================================================= */

function setupQuickActions() {

    if (!currentGuildId) {

        currentGuildId =
            localStorage.getItem(
                SERVER_STORAGE_KEY
            );

    }


    if (!currentGuildId) {

        return;

    }


    localStorage.setItem(
        SERVER_STORAGE_KEY,
        String(currentGuildId)
    );



    const quickChannels =
    document.getElementById(
        "quick-channels"
    );


    if (quickChannels) {

        quickChannels.href =
            `/servers/${encodeURIComponent(
                currentGuildId
            )}/channels`;

    }


    const quickMembers =
    document.getElementById(
        "quick-members"
    );


    if (quickMembers) {

        quickMembers.href =
            `/servers/${encodeURIComponent(
                currentGuildId
            )}/members`;

    }


    const quickServer =
        document.getElementById(
            "quick-server"
        );


    if (quickServer) {

        quickServer.href =
            `/servers/${encodeURIComponent(
                currentGuildId
            )}`;

    }


    const quickActivity =
        document.getElementById(
            "quick-activity"
        );


    if (quickActivity) {

        quickActivity.href =
            `/servers/${encodeURIComponent(
                currentGuildId
            )}/activity`;

    }

}


/* =========================================================
   SERVER HEALTH
========================================================= */

async function loadServerHealth() {

    if (!currentGuildId) {

        return;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(
                    currentGuildId
                )}/health`,
                {
                    cache:
                        "no-store",

                    credentials:
                        "same-origin"
                }
            );


        const result =
            await response.json();


        if (
            !response.ok
            ||
            !result.success
        ) {

            throw new Error(
                result.error
                ||
                `HTTP ${response.status}`
            );

        }


        updateServerHealth(
            result.health || {}
        );

    }

    catch (error) {

        console.error(
            "Server health error:",
            error
        );


        updateServerHealth({

            discord_connected:
                false,

            discord_ready:
                false,

            status:
                "offline"

        });

    }

}


function updateServerHealth(
    health
) {

    const connected =
        health.discord_connected === true;


    const ready =
        health.discord_ready === true;


    const status =
        String(
            health.status
            ||
            "unknown"
        ).toLowerCase();


    let healthText =
        "Offline";


    if (
        status ===
        "healthy"
    ) {

        healthText =
            "Healthy";

    }

    else if (
        status ===
        "degraded"
    ) {

        healthText =
            "Degraded";

    }

    else if (
        status ===
        "poor"
    ) {

        healthText =
            "Poor";

    }


    setText(
        "health-live-text",
        connected && ready
            ? healthText
            : "Offline"
    );


    const liveDot =
        document.getElementById(
            "health-live-dot"
        );


    if (liveDot) {

        liveDot.classList.toggle(
            "online",
            connected && ready
        );


        liveDot.classList.toggle(
            "offline",
            !(connected && ready)
        );

    }


    setText(
        "health-bot",
        ready
            ? `${Number(
                health.bot_latency_ms || 0
            )} ms`
            : "Offline"
    );


    setText(
        "health-logger",
        health.logger === "active"
            ? "Active"
            : health.logger === "idle"
                ? "Idle"
                : connected
                    ? "Ready"
                    : "Offline"
    );


    setText(
        "health-members",
        Number(
            health.members || 0
        ).toLocaleString()
    );


    setText(
        "health-channels",
        Number(
            health.channels || 0
        ).toLocaleString()
    );


    setText(
        "health-events",
        Number(
            health.events || 0
        ).toLocaleString()
    );


    setText(
        "health-updated",
        new Date().toLocaleTimeString()
    );

}  
/* =========================================================
   ACTIVITY FILTER
========================================================= */

function filterActivity(
    filter
) {

    const items =
        document.querySelectorAll(
            "#activity-list .activity"
        );


    document
        .querySelectorAll(
            ".activity-filter"
        )
        .forEach(
            button => {

                button.classList.toggle(
                    "active",
                    button.dataset.filter ===
                    filter
                );

            }
        );


    items.forEach(
        item => {

            if (filter === "all") {

                item.style.display =
                    "";

                return;

            }


            const type =
                String(
                    item.dataset.eventType ||
                    ""
                ).toLowerCase();


            const category =
                String(
                    item.querySelector(
                        ".activity-category"
                    )?.textContent ||
                    ""
                ).toLowerCase();


            const matches =
                type.includes(filter) ||
                category.includes(filter);


            item.style.display =
                matches
                    ? ""
                    : "none";

        }
    );

}


/* =========================================================
   DASHBOARD NAVIGATION
========================================================= */

function setupServerNavigation() {

    if (!currentGuildId) {

        currentGuildId =
            localStorage.getItem(
                SERVER_STORAGE_KEY
            );

    }


    if (!currentGuildId) {

        return;

    }


    const guildId =
        encodeURIComponent(
            String(currentGuildId)
        );


    const routes = {

        "nav-server":
            `/servers/${guildId}`,

        "nav-members":
            `/servers/${guildId}/members`,

        "nav-channels":
            `/servers/${guildId}/channels`,

        "nav-roles":
            `/servers/${guildId}/roles`,

        "nav-activity":
            `/servers/${guildId}/activity`,

        "nav-events":
            `/servers/${guildId}/events`,

        "nav-moderation":
            `/servers/${guildId}/moderation`,

        "nav-settings":
            `/servers/${guildId}/settings`

    };


    Object.entries(
        routes
    ).forEach(
        ([id, url]) => {

            const element =
                document.getElementById(
                    id
                );


            if (!element) {

                return;

            }


            element.href =
                url;


            /*
             * Remove old click handlers
             * by cloning the element.
             *
             * This prevents older dashboard
             * navigation code from interfering.
             */

            const replacement =
                element.cloneNode(
                    true
                );


            element.parentNode.replaceChild(
                replacement,
                element
            );


            replacement.addEventListener(
                "click",
                event => {

                    /*
                     * Save the selected server
                     * before leaving the page.
                     */

                    localStorage.setItem(
                        SERVER_STORAGE_KEY,
                        String(
                            currentGuildId
                        )
                    );

                }
            );

        }
    );

}


/* =========================================================
   ENHANCED DASHBOARD UPDATE
========================================================= */

function updateEnhancedDashboard(
    dashboard
) {

    updateServerHealth(
        dashboard
    );

    setupQuickActions();

    setupServerNavigation();

}


/* =========================================================
   REFRESH INDICATOR
========================================================= */

function updateRefreshIndicator() {

    const updated =
        document.getElementById(
            "health-updated"
        );


    if (updated) {

        updated.textContent =
            new Date().toLocaleTimeString();

    }

}



/* =========================================================
   BOT AVATAR
========================================================= */

async function loadBotAvatar() {

    const avatar =
        document.getElementById(
            "bot-avatar"
        );


    const fallback =
        document.getElementById(
            "bot-avatar-fallback"
        );


    if (!avatar) {

        return;

    }


    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache: "no-store",
                    credentials: "same-origin"
                }
            );


        if (!response.ok) {

            return;

        }


        const data =
            await response.json();


        if (
            data.bot_avatar
        ) {

            avatar.onload =
                () => {

                    avatar.style.display =
                        "block";


                    if (fallback) {

                        fallback.style.display =
                            "none";

                    }

                };


            avatar.onerror =
                () => {

                    avatar.style.display =
                        "none";


                    if (fallback) {

                        fallback.style.display =
                            "flex";

                    }

                };


            avatar.src =
                data.bot_avatar;

        }

    }

    catch (error) {

        console.error(
            "Failed to load bot avatar:",
            error
        );

    }

}


// =========================================================
// OVERVIEW DATA
// =========================================================

async function loadOverviewData() {

    if (!currentGuildId) {

        console.warn(
            "[Dashboard] No guild ID available."
        );

        return;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(currentGuildId)}/overview`,
                {
                    credentials: "same-origin"
                }
            );


        if (!response.ok) {

            throw new Error(
                `HTTP ${response.status}`
            );

        }


        const result =
            await response.json();


        if (!result.success) {

            throw new Error(
                result.error ||
                "Unable to load overview."
            );

        }


        window.SERVER_OVERVIEW =
            result;


        updateOverviewCards(result);
        updateServerHeader(result);
        updateServerInfo(result);


    }
    catch (error) {

        console.error(
            "[Dashboard] Overview failed:",
            error
        );

    }

}

// =========================================================
// OVERVIEW CARDS
// =========================================================

function updateOverviewCards(
    data
) {

    const members =
        data.members || {};


    const channels =
        data.channels || {};


    const roles =
        data.roles || {};


    const server =
        data.server || {};


    setText(
        "member-count",
        Number(
            members.count || 0
        ).toLocaleString()
    );


    setText(
        "channel-count",
        Number(
            channels.count || 0
        ).toLocaleString()
    );


    setText(
        "role-count",
        Number(
            roles.count || 0
        ).toLocaleString()
    );


    setText(
        "server-members",
        Number(
            server.member_count ||
            members.count ||
            0
        ).toLocaleString()
    );


    setText(
        "online-members",
        Number(
            members.online || 0
        ).toLocaleString()
    );


    setText(
        "human-members",
        Number(
            members.humans || 0
        ).toLocaleString()
    );


    setText(
        "bot-members",
        Number(
            members.bots || 0
        ).toLocaleString()
    );


    setText(
        "text-channels",
        Number(
            channels.text || 0
        ).toLocaleString()
    );


    setText(
        "voice-channels",
        Number(
            channels.voice || 0
        ).toLocaleString()
    );


    setText(
        "categories",
        Number(
            channels.categories || 0
        ).toLocaleString()
    );


    const updated =
        document.getElementById(
            "overview-last-updated"
        );


    if (updated) {

        updated.textContent =
            `Updated ${new Date().toLocaleTimeString()}`;

    }
}


// =========================================================
// SERVER HEADER
// =========================================================

function updateServerHeader(
    data
) {

    const server =
        data.server || {};


    const name =
        server.name ||
        "Unknown Server";


    setText(
        "server-name",
        name
    );


    setText(
        "server-subtitle",
        name
    );


    setText(
        "server-id",
        server.id ||
        currentGuildId ||
        "--"
    );


    const serverIcon =
        document.getElementById(
            "server-icon"
        );


    if (serverIcon) {
        if (server.icon) {
            serverIcon.src = server.icon;
            serverIcon.style.display = "block";
            serverIcon.onerror = () => { serverIcon.style.display = "none"; };
        } else {
            serverIcon.style.display = "none";
        }
    }


    const avatar =
        document.getElementById(
            "server-avatar"
        );


    if (
        avatar &&
        server.icon
    ) {

        avatar.innerHTML = `
            <img
                src="${escapeHtml(server.icon)}"
                alt="${escapeHtml(name)}"
            >
        `;

    }

}


// =========================================================
// LIVE OVERVIEW REFRESH
// =========================================================

let overviewRefreshTimer =
    null;


function startOverviewRefresh() {

    if (
        overviewRefreshTimer
    ) {

        clearInterval(
            overviewRefreshTimer
        );

    }


    overviewRefreshTimer =
        setInterval(
            function() {

                loadOverviewData();

            },
            30000
        );

}


document.addEventListener(
    "DOMContentLoaded",
    function() {

        startOverviewRefresh();

    }
);


