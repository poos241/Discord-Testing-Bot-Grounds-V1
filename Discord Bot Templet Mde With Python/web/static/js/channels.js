/* =========================================================
   CHANNELS PAGE
========================================================= */

const guildId =
    window.GUILD_ID
        ? String(window.GUILD_ID)
        : null;


let allChannels = [];

let currentFilter =
    "all";


/* =========================================================
   START
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        setupFilters();

        setupSearch();

        setupRefresh();

        loadBotAvatar();

        loadChannels();

        // Silent auto-refresh every 45s
        setInterval(function() {
            loadChannels(true).catch(function() {});
        }, 45000);

    }
);


/* =========================================================
   HELPERS
========================================================= */

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


function setText(
    id,
    value
) {

    const element =
        document.getElementById(
            id
        );


    if (element) {

        element.textContent =
            value;

    }

}


function getChannelType(
    channel
) {

    const type =
        String(
            channel.type ||
            ""
        ).toLowerCase();


    if (
        type.includes("text")
    ) {

        return "text";

    }


    if (
        type.includes("voice")
    ) {

        return "voice";

    }


    if (
        type.includes("category")
    ) {

        return "category";

    }


    if (
        type.includes("forum")
    ) {

        return "text";

    }


    if (
        type.includes("stage")
    ) {

        return "voice";

    }


    return "other";

}


function getChannelIcon(
    channel
) {

    const type =
        getChannelType(
            channel
        );


    if (
        type === "text"
    ) {

        return "#";

    }


    if (
        type === "voice"
    ) {

        return "🔊";

    }


    if (
        type === "category"
    ) {

        return "📁";

    }


    return "▤";

}


function getChannelTypeLabel(
    channel
) {

    const type =
        getChannelType(
            channel
        );


    if (
        type === "text"
    ) {

        return "Text";

    }


    if (
        type === "voice"
    ) {

        return "Voice";

    }


    if (
        type === "category"
    ) {

        return "Category";

    }


    return String(
        channel.type ||
        "Channel"
    );

}


/* =========================================================
   LOAD CHANNELS
========================================================= */

async function loadChannels(silent) {

    const list =
        document.getElementById(
            "channels-list"
        );


    if (!list) {

        return;

    }


    if (!guildId) {

        list.innerHTML = `

            <div class="channel-empty">
                No server selected.
            </div>

        `;

        return;

    }


    if (!silent) {
        list.innerHTML = `

        <div class="channels-loading">

            <div class="channels-spinner"></div>

            <span>
                Loading channels...
            </span>

        </div>

        `;
    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(guildId)}/channels`,
                {
                    cache: "no-store",
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


        if (
            result.success === false
        ) {

            throw new Error(
                result.error ||
                "Unable to load channels."
            );

        }


        allChannels =
            Array.isArray(
                result.channels
            )
                ? result.channels
                : [];


        updateServerHeader(
            result
        );


        updateStats();

        renderChannels();


    }

    catch (error) {

        console.error(
            "[Channels] Failed:",
            error
        );


        list.innerHTML = `

            <div class="channel-empty">

                <strong>
                    Failed to load channels
                </strong>

                <div style="margin-top:8px;">
                    ${escapeHtml(
                        error.message
                    )}
                </div>

            </div>

        `;

    }

}


/* =========================================================
   SERVER HEADER
========================================================= */

function updateServerHeader(
    result
) {

    const name =
        result.guild_name ||
        "Discord Server";


    setText(
        "server-name",
        name
    );


    if (
        result.guild_icon
    ) {

        setServerAvatar(
            result.guild_icon,
            name
        );

        return;

    }


    if (
        guildId
    ) {

        fetch(
            `/api/servers/${encodeURIComponent(guildId)}`,
            {
                cache: "no-store",
                credentials: "same-origin"
            }
        )

            .then(
                response => {

                    if (!response.ok) {

                        return null;

                    }

                    return response.json();

                }
            )

            .then(
                data => {

                    if (
                        data &&
                        data.server &&
                        data.server.icon
                    ) {

                        setServerAvatar(
                            data.server.icon,
                            data.server.name ||
                            name
                        );

                    }

                    else if (
                        data &&
                        data.icon
                    ) {

                        setServerAvatar(
                            data.icon,
                            name
                        );

                    }

                }
            )

            .catch(
                () => {}
            );

    }

}


function setServerAvatar(
    icon,
    name
) {

    const container =
        document.getElementById(
            "server-avatar"
        );


    if (!container) {

        return;

    }


    container.innerHTML = `

        <img
            src="${escapeHtml(icon)}"
            alt="${escapeHtml(name)}"
        >

    `;


    const image =
        container.querySelector(
            "img"
        );


    if (image) {

        image.onerror =
            () => {

                container.textContent =
                    getInitials(
                        name
                    );

            };

    }

}


function getInitials(
    name
) {

    const value =
        String(
            name ||
            "Server"
        ).trim();


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
        ).toUpperCase();

    }


    return value
        .substring(
            0,
            2
        )
        .toUpperCase();

}


/* =========================================================
   STATS
========================================================= */

function updateStats() {

    let text =
        0;

    let voice =
        0;

    let categories =
        0;


    allChannels.forEach(
        channel => {

            const type =
                getChannelType(
                    channel
                );


            if (
                type === "text"
            ) {

                text++;

            }

            else if (
                type === "voice"
            ) {

                voice++;

            }

            else if (
                type === "category"
            ) {

                categories++;

            }

        }
    );


    setText(
        "text-count",
        text.toLocaleString()
    );


    setText(
        "voice-count",
        voice.toLocaleString()
    );


    setText(
        "category-count",
        categories.toLocaleString()
    );


    setText(
        "total-count",
        allChannels.length.toLocaleString()
    );

}


/* =========================================================
   FILTERS
========================================================= */

function setupFilters() {

    document
        .querySelectorAll(
            ".channel-filter"
        )
        .forEach(
            button => {

                button.addEventListener(
                    "click",
                    () => {

                        currentFilter =
                            button.dataset.filter ||
                            "all";


                        document
                            .querySelectorAll(
                                ".channel-filter"
                            )
                            .forEach(
                                item => {

                                    item.classList.toggle(
                                        "active",
                                        item === button
                                    );

                                }
                            );


                        renderChannels();

                    }
                );

            }
        );

}


function setupSearch() {

    const search =
        document.getElementById(
            "channel-search"
        );


    if (!search) {

        return;

    }


    search.addEventListener(
        "input",
        () => {

            renderChannels();

        }
    );

}


/* =========================================================
   RENDER
========================================================= */

function renderChannels() {

    const list =
        document.getElementById(
            "channels-list"
        );


    const resultCount =
        document.getElementById(
            "channel-result-count"
        );


    if (!list) {

        return;

    }


    const searchElement =
        document.getElementById(
            "channel-search"
        );


    const search =
        searchElement
            ? searchElement.value
                .trim()
                .toLowerCase()
            : "";


    const filtered =
        allChannels.filter(
            channel => {

                const type =
                    getChannelType(
                        channel
                    );


                if (
                    currentFilter !==
                    "all" &&
                    type !==
                    currentFilter
                ) {

                    return false;

                }


                if (
                    search &&
                    !String(
                        channel.name ||
                        ""
                    )
                        .toLowerCase()
                        .includes(
                            search
                        )
                ) {

                    return false;

                }


                return true;

            }
        );


    if (resultCount) {

        resultCount.textContent =
            `${filtered.length.toLocaleString()} of ${
                allChannels.length.toLocaleString()
            } channels`;

    }


    if (!filtered.length) {

        list.innerHTML = `

            <div class="channel-empty">

                No channels match your search.

            </div>

        `;

        return;

    }


    list.innerHTML =
        filtered
            .map(
                createChannelRow
            )
            .join("");


    list
        .querySelectorAll(
            ".channel-row"
        )
        .forEach(
            row => {

                row.addEventListener(
                    "click",
                    () => {

                        openChannel(
                            row.dataset.channelId
                        );

                    }
                );

            }
        );

}


/* =========================================================
   CHANNEL ROW
========================================================= */

function createChannelRow(
    channel
) {

    const id =
        String(
            channel.id ||
            ""
        );


    const name =
        String(
            channel.name ||
            "Unnamed Channel"
        );


    const type =
        getChannelTypeLabel(
            channel
        );


    const category =
        channel.category ||
        "No category";


    const position =
        Number(
            channel.position || 0
        );


    const nsfw =
        channel.nsfw === true;


    return `

        <div
            class="channel-row"
            data-channel-id="${escapeHtml(id)}"
        >

            <div class="channel-icon">

                ${getChannelIcon(
                    channel
                )}

            </div>


            <div class="channel-main">

                <div class="channel-name">

                    ${escapeHtml(name)}

                </div>

                <div class="channel-meta">

                    ID:
                    ${escapeHtml(id)}

                </div>

            </div>


            <div class="channel-category">

                ${escapeHtml(category)}

            </div>


            <div class="channel-type">

                ${escapeHtml(type)}

            </div>


            <div class="channel-position">

                ${
                    nsfw
                        ? `
                            <span class="channel-nsfw">
                                NSFW
                            </span>
                        `
                        : `#${position}`
                }

            </div>

        </div>

    `;

}


/* =========================================================
   CHANNEL DETAILS
========================================================= */

function openChannel(
    channelId
) {

    if (!channelId || !guildId) {

        return;

    }


    window.location.href =
        `/servers/${encodeURIComponent(
            guildId
        )}/channels/${encodeURIComponent(
            channelId
        )}`;

}


/* =========================================================
   REFRESH
========================================================= */

function setupRefresh() {

    const button =
        document.getElementById(
            "refresh-channels"
        );


    if (!button) {

        return;

    }


    button.addEventListener(
        "click",
        async () => {

            button.disabled =
                true;


            button.textContent =
                "↻ Loading...";


            await loadChannels();


            button.disabled =
                false;


            button.textContent =
                "↻ Refresh";

        }
    );

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
            !data.bot_avatar
        ) {

            return;

        }


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

            };


        avatar.src =
            data.bot_avatar;

    }

    catch (error) {

        console.warn(
            "[Channels] Bot avatar failed:",
            error
        );

    }

}