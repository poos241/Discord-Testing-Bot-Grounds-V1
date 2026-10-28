/* =========================================================
   LIVE VOICE VIEWER PAGE
   Polls /api/servers/<guild_id>/voice every 15 seconds.
   Voice membership changes fast, so this polls more often
   than the channels page (45s). Polling pauses while the
   tab is hidden and resumes on return.
========================================================= */

const guildId =
    window.GUILD_ID
        ? String(window.GUILD_ID)
        : null;


let lastVoiceData = null;


/* =========================================================
   START
========================================================= */

document.addEventListener(
    "DOMContentLoaded",
    () => {

        setupRefresh();

        loadVoice().catch(function(err) {

            const listEl =
                document.getElementById("voice-list");

            if (listEl) {
                listEl.innerHTML =
                    '<div class="voice-error">Could not load voice channels: ' +
                    escapeHtml(err.message || err) +
                    '</div>';
            }

        });

        // Silent auto-refresh every 15s, skipped while hidden.
        setInterval(function() {
            if (document.hidden) {
                return;
            }
            loadVoice(true).catch(function() {});
        }, 15000);

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


function setupRefresh() {

    const button =
        document.getElementById("refresh-voice");

    if (!button) {
        return;
    }

    button.addEventListener(
        "click",
        () => {
            loadVoice().catch(function(err) {

                const listEl =
                    document.getElementById("voice-list");

                if (listEl) {
                    listEl.innerHTML =
                        '<div class="voice-error">Could not load voice channels: ' +
                        escapeHtml(err.message || err) +
                        '</div>';
                }

            });
        }
    );

}


function memberBadges(
    member
) {

    const badges = [];

    if (member.bot) {
        badges.push('<span class="voice-badge voice-badge-bot">BOT</span>');
    }

    if (member.deafened) {
        badges.push('<span class="voice-badge" title="Deafened">🔇 Deaf</span>');
    } else if (member.muted) {
        badges.push('<span class="voice-badge" title="Muted">🔇 Muted</span>');
    }

    if (member.streaming) {
        badges.push('<span class="voice-badge voice-badge-live" title="Streaming">● Live</span>');
    }

    if (member.video) {
        badges.push('<span class="voice-badge" title="Video on">📹 Video</span>');
    }

    return badges.join(" ");

}


function memberRow(
    member
) {

    const avatar = member.avatar_url
        ? '<img class="voice-member-avatar" src="' + escapeHtml(member.avatar_url) + '" alt="">'
        : '<span class="voice-member-avatar voice-member-fallback">' +
            escapeHtml((member.display_name || member.name || "?").slice(0, 1).toUpperCase()) +
          '</span>';

    return '' +
        '<div class="voice-member">' +
            avatar +
            '<span class="voice-member-name">' +
                escapeHtml(member.display_name || member.name) +
            '</span>' +
            memberBadges(member) +
        '</div>';

}


function channelCard(
    channel
) {

    const occupied =
        channel.member_count > 0;

    const limitText =
        channel.user_limit > 0
            ? " / " + channel.user_limit
            : "";

    const typeLabel =
        channel.type === "stage_voice"
            ? "Stage"
            : "Voice";

    const categoryText =
        channel.category
            ? '<span class="voice-channel-category">' +
                escapeHtml(channel.category) +
              '</span>'
            : "";

    const membersHtml =
        occupied
            ? channel.members.map(memberRow).join("")
            : '<div class="voice-empty-note">Empty — click Join to hop in.</div>';

    return '' +
        '<article class="voice-channel' +
            (occupied ? ' voice-channel-occupied' : '') +
        '">' +
            '<div class="voice-channel-head">' +
                '<div>' +
                    '<span class="voice-channel-icon">🔊</span> ' +
                    '<strong class="voice-channel-name">' +
                        escapeHtml(channel.name) +
                    '</strong> ' +
                    '<span class="voice-channel-type">' + typeLabel + '</span> ' +
                    categoryText +
                '</div>' +
                '<div class="voice-channel-head-right">' +
                    '<span class="voice-channel-count">' +
                        channel.member_count + limitText +
                    '</span> ' +
                    '<a class="voice-join-button" href="' +
                        escapeHtml(channel.join_url) +
                        '" target="_blank" rel="noopener">' +
                        'Join →' +
                    '</a>' +
                '</div>' +
            '</div>' +
            '<div class="voice-members">' +
                membersHtml +
            '</div>' +
        '</article>';

}


/* =========================================================
   LOAD
========================================================= */

async function loadVoice(
    silent
) {

    const listEl =
        document.getElementById("voice-list");

    const resultEl =
        document.getElementById("voice-result-count");

    if (!guildId) {

        if (listEl) {
            listEl.innerHTML =
                '<div class="voice-error">No server selected.</div>';
        }

        return;

    }

    if (!silent && listEl && !lastVoiceData) {

        listEl.innerHTML =
            '<div class="channels-loading">' +
                '<div class="channels-spinner"></div>' +
                '<span>Loading voice channels...</span>' +
            '</div>';

    }

    const response = await fetch(
        "/api/servers/" + encodeURIComponent(guildId) + "/voice",
        { cache: "no-store", credentials: "same-origin" }
    );

    const result = await response.json();

    if (!response.ok || !result.success) {

        throw new Error(
            result.error || ("HTTP " + response.status)
        );

    }

    lastVoiceData = result;

    const nameEl =
        document.getElementById("server-name");

    if (nameEl && result.guild_name) {
        nameEl.textContent = result.guild_name;
    }

    const inVoiceEl =
        document.getElementById("in-voice-count");

    if (inVoiceEl) {
        inVoiceEl.textContent = result.total_in_voice;
    }

    const occupiedEl =
        document.getElementById("occupied-count");

    if (occupiedEl) {
        occupiedEl.textContent = result.occupied_channel_count;
    }

    const channelCountEl =
        document.getElementById("voice-channel-count");

    if (channelCountEl) {
        channelCountEl.textContent = result.count;
    }

    const updatedEl =
        document.getElementById("last-updated");

    if (updatedEl) {
        updatedEl.textContent =
            new Date().toLocaleTimeString();
    }

    // Occupied channels first, then empty ones, each in
    // position order, so the live action is at the top.
    const ordered = (result.channels || []).slice().sort(
        function(a, b) {
            if ((a.member_count > 0) !== (b.member_count > 0)) {
                return a.member_count > 0 ? -1 : 1;
            }
            return (a.position || 0) - (b.position || 0);
        }
    );

    if (resultEl) {

        if (result.total_in_voice === 0) {
            resultEl.textContent =
                "Nobody is in voice right now — join a channel below.";
        } else {
            resultEl.textContent =
                result.total_in_voice + " in voice across " +
                result.occupied_channel_count + " channel(s)";
        }

    }

    if (listEl) {

        if (ordered.length === 0) {
            listEl.innerHTML =
                '<div class="voice-error">This server has no voice channels.</div>';
        } else {
            listEl.innerHTML =
                ordered.map(channelCard).join("");
        }

    }

}
