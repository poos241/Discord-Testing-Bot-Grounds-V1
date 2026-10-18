const rolesPage =
    document.getElementById(
        "roles-page"
    );


const guildId =
    rolesPage?.dataset.guildId ||
    null;


let roles = [];


/* =========================================================
   START
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        setupRoleControls();

        await loadRoles();

    }
);


/* =========================================================
   CONTROLS
========================================================= */

function setupRoleControls() {

    const search =
        document.getElementById(
            "role-search"
        );


    const filter =
        document.getElementById(
            "role-filter"
        );


    const refresh =
        document.getElementById(
            "refresh-roles"
        );


    if (search) {

        search.addEventListener(
            "input",
            renderRoles
        );

    }


    if (filter) {

        filter.addEventListener(
            "change",
            renderRoles
        );

    }


    if (refresh) {

        refresh.addEventListener(
            "click",
            loadRoles
        );

    }


    const close =
        document.getElementById(
            "role-modal-close"
        );


    const backdrop =
        document.getElementById(
            "role-modal-backdrop"
        );


    if (close) {

        close.addEventListener(
            "click",
            closeRoleModal
        );

    }


    if (backdrop) {

        backdrop.addEventListener(
            "click",
            closeRoleModal
        );

    }


    document.addEventListener(
        "keydown",
        event => {

            if (
                event.key === "Escape"
            ) {

                closeRoleModal();

            }

        }
    );

}


/* =========================================================
   LOAD
========================================================= */

async function loadRoles() {

    if (!guildId) {

        showRoleError(
            "No server was selected."
        );

        return;

    }


    const list =
        document.getElementById(
            "roles-list"
        );


    if (list) {

        list.innerHTML = `

            <div class="roles-loading">

                <div class="roles-spinner"></div>

                <span>
                    Loading roles...
                </span>

            </div>

        `;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(guildId)}/roles`,
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


        roles =
            Array.isArray(
                result.roles
            )
                ? result.roles
                : [];


        setText(
            "roles-server-name",
            result.guild_name ||
            "Discord Server"
        );


        setText(
            "roles-server-id",
            result.guild_id ||
            guildId
        );


        setText(
            "roles-total",
            roles.length.toLocaleString()
        );


        renderRoles();

    }

    catch (error) {

        console.error(
            "[Roles] Failed to load:",
            error
        );


        showRoleError(
            error.message
        );

    }

}


/* =========================================================
   RENDER
========================================================= */

function renderRoles() {

    const list =
        document.getElementById(
            "roles-list"
        );


    if (!list) {

        return;

    }


    const search =
        String(
            document.getElementById(
                "role-search"
            )?.value ||
            ""
        )
        .trim()
        .toLowerCase();


    const filter =
        document.getElementById(
            "role-filter"
        )?.value ||
        "all";


    const filtered =
        roles.filter(
            role => {

                const name =
                    String(
                        role.name ||
                        ""
                    )
                    .toLowerCase();


                if (
                    search &&
                    !name.includes(
                        search
                    )
                ) {

                    return false;

                }


                if (
                    filter === "custom" &&
                    role.managed
                ) {

                    return false;

                }


                if (
                    filter === "managed" &&
                    !role.managed
                ) {

                    return false;

                }


                if (
                    filter === "admin" &&
                    !role.permissions?.includes(
                        "administrator"
                    )
                ) {

                    return false;

                }


                if (
                    filter === "mentionable" &&
                    !role.mentionable
                ) {

                    return false;

                }


                return true;

            }
        );


    setText(
        "roles-visible-count",
        `${filtered.length} of ${roles.length} roles`
    );


    if (!filtered.length) {

        list.innerHTML = `

            <div class="roles-empty">

                <div>
                    ◇
                </div>

                <strong>
                    No roles found
                </strong>

                <span>
                    Try changing your search or filter.
                </span>

            </div>

        `;

        return;

    }


    list.innerHTML =
        filtered
            .map(
                createRoleCard
            )
            .join("");


    list
        .querySelectorAll(
            "[data-role-id]"
        )
        .forEach(
            card => {

                card.addEventListener(
                    "click",
                    () => {

                        openRoleDetails(
                            card.dataset.roleId
                        );

                    }
                );

            }
        );

}


/* =========================================================
   ROLE CARD
========================================================= */

function createRoleCard(
    role
) {

    const color =
        normalizeRoleColor(
            role.color_value
        );


    const permissions =
        Array.isArray(
            role.permissions
        )
            ? role.permissions
            : [];


    const admin =
        permissions.includes(
            "administrator"
        );


    const badges = [];


    if (role.managed) {

        badges.push(
            `<span class="role-badge managed">Managed</span>`
        );

    }


    if (admin) {

        badges.push(
            `<span class="role-badge admin">Administrator</span>`
        );

    }


    if (role.hoist) {

        badges.push(
            `<span class="role-badge">Hoisted</span>`
        );

    }


    if (role.mentionable) {

        badges.push(
            `<span class="role-badge">Mentionable</span>`
        );

    }


    return `

        <button
            type="button"
            class="role-card"
            data-role-id="${escapeHtml(role.id)}"
        >

            <div
                class="role-color"
                style="background:${color};"
            ></div>


            <div class="role-main">

                <div class="role-name-row">

                    <strong>
                        ${escapeHtml(
                            role.name
                        )}
                    </strong>

                    ${
                        role.name === "@everyone"
                            ? `
                                <span class="role-badge everyone">
                                    Default
                                </span>
                            `
                            : ""
                    }

                </div>


                <div class="role-meta">

                    Position
                    ${Number(
                        role.position
                    )}

                    ·

                    ${Number(
                        role.member_count || 0
                    ).toLocaleString()}

                    members

                </div>


                <div class="role-badges">

                    ${badges.join("")}

                </div>

            </div>


            <div class="role-permission-count">

                <strong>
                    ${Number(
                        role.permission_count || 0
                    )}
                </strong>

                <span>
                    permissions
                </span>

            </div>


            <div class="role-arrow">
                →
            </div>

        </button>

    `;

}


/* =========================================================
   ROLE DETAILS
========================================================= */

async function openRoleDetails(
    roleId
) {

    if (!roleId || !guildId) {

        return;

    }


    const role =
        roles.find(
            item =>
                String(item.id) ===
                String(roleId)
        );


    if (!role) {

        return;

    }


    openRoleModal();


    setText(
        "role-modal-name",
        role.name
    );


    setText(
        "role-modal-id",
        role.id
    );


    setText(
        "role-modal-position",
        role.position
    );


    setText(
        "role-modal-members",
        Number(
            role.member_count || 0
        ).toLocaleString()
    );


    setText(
        "role-modal-permission-count",
        Number(
            role.permission_count || 0
        ).toLocaleString()
    );


    const color =
        normalizeRoleColor(
            role.color_value
        );


    const colorElement =
        document.getElementById(
            "role-modal-color"
        );


    if (colorElement) {

        colorElement.style.background =
            color;

    }


    renderRoleSettings(
        role
    );


    renderRolePermissions(
        role.permissions
    );


    const members =
        document.getElementById(
            "role-modal-member-list"
        );


    if (members) {

        members.innerHTML = `

            <div class="role-detail-loading">

                Loading members...

            </div>

        `;

    }


    try {

        const response =
            await fetch(
                `/api/servers/${encodeURIComponent(guildId)}/roles/${encodeURIComponent(roleId)}/details`,
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


        const detailRole =
            result.role ||
            role;


        renderRoleSettings(
            detailRole
        );


        renderRolePermissions(
            detailRole.permissions
        );


        renderRoleMembers(
            detailRole.members
        );

    }

    catch (error) {

        console.error(
            "[Roles] Details failed:",
            error
        );


        if (members) {

            members.innerHTML = `

                <div class="role-detail-error">

                    Failed to load members.

                    <small>
                        ${escapeHtml(
                            error.message
                        )}
                    </small>

                </div>

            `;

        }

    }

}


/* =========================================================
   SETTINGS
========================================================= */

function renderRoleSettings(
    role
) {

    const container =
        document.getElementById(
            "role-modal-settings"
        );


    if (!container) {

        return;

    }


    const settings = [

        [
            "Managed",
            role.managed
        ],

        [
            "Hoisted",
            role.hoist
        ],

        [
            "Mentionable",
            role.mentionable
        ]

    ];


    container.innerHTML =
        settings
            .map(
                ([label, value]) => `

                    <div class="role-setting">

                        <span>
                            ${label}
                        </span>

                        <strong
                            class="${
                                value
                                    ? "enabled"
                                    : "disabled"
                            }"
                        >
                            ${
                                value
                                    ? "Yes"
                                    : "No"
                            }
                        </strong>

                    </div>

                `
            )
            .join("");

}


/* =========================================================
   PERMISSIONS
========================================================= */

function renderRolePermissions(
    permissions
) {

    const container =
        document.getElementById(
            "role-modal-permissions"
        );


    if (!container) {

        return;

    }


    if (
        !Array.isArray(
            permissions
        ) ||
        !permissions.length
    ) {

        container.innerHTML = `

            <div class="role-no-permissions">

                No enabled permissions.

            </div>

        `;

        return;

    }


    container.innerHTML =
        permissions
            .map(
                permission => `

                    <span class="permission-chip">

                        ${escapeHtml(
                            formatPermission(
                                permission
                            )
                        )}

                    </span>

                `
            )
            .join("");

}


/* =========================================================
   MEMBERS
========================================================= */

function renderRoleMembers(
    members
) {

    const container =
        document.getElementById(
            "role-modal-member-list"
        );


    if (!container) {

        return;

    }


    if (
        !Array.isArray(
            members
        ) ||
        !members.length
    ) {

        container.innerHTML = `

            <div class="role-no-members">

                No members have this role.

            </div>

        `;

        return;

    }


    container.innerHTML =
        members
            .map(
                member => `

                    <div class="role-member">

                        <div class="role-member-avatar">

                            ${escapeHtml(
                                getInitials(
                                    member.display_name ||
                                    member.username
                                )
                            )}

                        </div>


                        <div class="role-member-info">

                            <strong>

                                ${escapeHtml(
                                    member.display_name ||
                                    member.username ||
                                    "Unknown"
                                )}

                            </strong>

                            <span>

                                @${escapeHtml(
                                    member.username ||
                                    "unknown"
                                )}

                            </span>

                        </div>


                        ${
                            member.bot
                                ? `
                                    <span class="role-member-bot">
                                        BOT
                                    </span>
                                `
                                : ""
                        }

                    </div>

                `
            )
            .join("");

}


/* =========================================================
   MODAL
========================================================= */

function openRoleModal() {

    const modal =
        document.getElementById(
            "role-modal"
        );


    if (!modal) {

        return;

    }


    modal.hidden =
        false;


    document.body.classList.add(
        "role-modal-open"
    );

}


function closeRoleModal() {

    const modal =
        document.getElementById(
            "role-modal"
        );


    if (!modal) {

        return;

    }


    modal.hidden =
        true;


    document.body.classList.remove(
        "role-modal-open"
    );

}


/* =========================================================
   ERROR
========================================================= */

function showRoleError(
    message
) {

    const list =
        document.getElementById(
            "roles-list"
        );


    if (!list) {

        return;

    }


    list.innerHTML = `

        <div class="roles-error">

            <strong>
                Unable to load roles
            </strong>

            <span>
                ${escapeHtml(
                    message ||
                    "Unknown error"
                )}
            </span>

            <button
                type="button"
                onclick="loadRoles()"
            >
                Try Again
            </button>

        </div>

    `;

}


/* =========================================================
   HELPERS
========================================================= */

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
            value ?? "--";

    }

}


function normalizeRoleColor(
    value
) {

    const number =
        Number(
            value || 0
        );


    if (!number) {

        return "#5865f2";

    }


    return `#${number
        .toString(16)
        .padStart(
            6,
            "0"
        )}`;

}


function formatPermission(
    value
) {

    return String(
        value ||
        ""
    )
        .replaceAll(
            "_",
            " "
        )
        .replace(
            /\b\w/g,
            char =>
                char.toUpperCase()
        );

}


function getInitials(
    name
) {

    const value =
        String(
            name ||
            "User"
        )
        .trim();


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