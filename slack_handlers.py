from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config import BOT_ADMIN_ID, HUDDLE_CHANNEL_ID, HUDDLE_USERGROUP_ID, LOG_CHANNEL_ID, REDACTED_SENTINEL, logger
from state import state
from leaderboard import format_reviewer_line

_seen_events: OrderedDict[str, None] = OrderedDict()
_SEEN_EVENTS_MAX = 50

if TYPE_CHECKING:
    from slack_bolt import App


def _display_name(user_obj: dict) -> str:

    profile = user_obj.get("profile", {})
    return (
        profile.get("display_name")
        or profile.get("real_name")
        or user_obj.get("real_name")
        or user_obj.get("name")
        or user_obj.get("id", "Unknown")
    )


def _announce_review(client, cert: dict, reviewer_slack_id: str) -> None:

    project_name = cert.get("projectName", "Unknown Project")
    project_type = cert.get("projectType", "Project")
    status = cert.get("status", "unknown")
    demo_url = cert.get("demoUrl", "")
    repo_url = cert.get("repoUrl", "")
    feedback = cert.get("reviewFeedback", "")
    cookies = cert.get("cookiesEarned")

    status_text = status.capitalize()

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{project_name}* ({project_type}) - *{status_text}*\n"
                    f"Reviewed by <@{reviewer_slack_id}>"
                ),
            },
        },
    ]

    links: list[str] = []
    if demo_url:
        links.append(f"<{demo_url}|Demo>")
    if repo_url:
        links.append(f"<{repo_url}|Repo>")
    if links:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "  •  ".join(links)}],
            }
        )

    if feedback:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"💬 {feedback}"}],
            }
        )

    if cookies and cookies != REDACTED_SENTINEL:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"🍪 {cookies} cookies earned"}
                ],
            }
        )

    try:
        client.chat_postMessage(
            channel=LOG_CHANNEL_ID,
            blocks=blocks,
            text=f"{project_name} - {status_text} by <@{reviewer_slack_id}>",
        )
    except Exception:
        logger.exception("Failed to announce review")




def _send_confirmation_dm(client, user_id: str, display_name: str, call_id: str) -> None:
    """Send a DM to the admin to ask if approve or ignore this huddle"""

    try:
        resp = client.chat_postMessage(
            channel=BOT_ADMIN_ID,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"🎧 *Huddle detected!*\n"
                            f"<@{user_id}> ({display_name}) just joined a huddle.\n"
                            f"Is this the review huddle in <#{HUDDLE_CHANNEL_ID}>?"
                        ),
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Approve"},
                            "style": "primary",
                            "action_id": "approve_huddle",
                            "value": call_id,
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "❌ Ignore"},
                            "style": "danger",
                            "action_id": "ignore_huddle",
                            "value": call_id,
                        },
                    ],
                },
            ],
            text=f"Huddle detected {display_name} joined. Approve or ignore?",
        )
        dm_ts = resp["ts"]
        state.set_pending(call_id, user_id, dm_ts)
        state.queue_pending_participant(user_id, display_name)
        logger.info(
            "Sent huddle confirmation DM for call_id=%s (triggered by %s)",
            call_id,
            display_name,
        )
    except Exception:
        logger.exception("Failed to send huddle confirmation DM")


def _start_approved_session(client, call_id: str) -> None:
    """Start the huddle session and retroactively add queued participants."""
    queued = state.get_pending_participants()
    state.start_session(call_id)

    for uid, name in queued.items():
        state.add_participant(uid, name)

    logger.info(
        "Huddle session approved and started (call_id=%s, %d participants)",
        call_id,
        state.participant_count(),
    )


    try:
        start_time = state.start_time
        start_ts = int(start_time.timestamp()) if start_time else 0
        participant_names = ", ".join(f"<@{uid}>" for uid in queued)
        resp = client.chat_postMessage(
            channel=LOG_CHANNEL_ID,
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Review Huddle Started!",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"A review huddle has kicked off in <#{HUDDLE_CHANNEL_ID}>!\n"
                            f"Started at <!date^{start_ts}^{{date_short_pretty}} at {{time}}|{start_time}>."
                            f"\n\nLet the reviews begin! :yay:"
                        ),
                    },
                },
            ],
            text="Review Huddle Started!",
        )
        state.announcement_ts = resp["ts"]
    except Exception:
        logger.exception("Failed to send huddle start announcement")

    for uid in queued:
        try:
            client.chat_postMessage(
                channel=LOG_CHANNEL_ID,
                text=f"<@{uid}> joined the huddle! ({state.participant_count()} in huddle)",
            )
        except Exception:
            logger.exception("Failed to send join message for %s", uid)



def handle_huddle_changed(event: dict, client) -> None:
    """sees when someone joins/leaves a huddle and updates the state"""

    user_obj = event.get("user", {})
    user_id = user_obj.get("id")
    if not user_id:
        return

    profile = user_obj.get("profile", {})
    huddle_state_value = profile.get("huddle_state", "")
    call_id = profile.get("huddle_state_call_id", "")
    display_name = _display_name(user_obj)

    in_huddle = huddle_state_value == "in_a_huddle"

    if in_huddle:
        _handle_huddle_join(client, user_id, call_id, display_name)
    else:
        _handle_huddle_leave(client, user_id, display_name)


def _handle_huddle_join(
    client, user_id: str, call_id: str, display_name: str
) -> None:
    """Process a user joining a huddle."""

    if state.active:
        if call_id != state.tracked_call_id:
            logger.debug(
                "Ignoring huddle join by %s — different call_id (%s != %s)",
                display_name,
                call_id,
                state.tracked_call_id,
            )
            return

        newly_added = state.add_participant(user_id, display_name)
        if newly_added:
            try:
                client.chat_postMessage(
                    channel=LOG_CHANNEL_ID,
                    text=f"<@{user_id}> joined the huddle! ({state.participant_count()} in huddle)",
                )
            except Exception:
                logger.exception("Failed to send join message")

        logger.info(
            "%s joined the huddle (%d total)", display_name, state.participant_count()
        )
        return

    if not state.is_usergroup_member(client, user_id, HUDDLE_USERGROUP_ID):
        logger.debug(
            "Ignoring huddle join by %s — not in usergroup %s",
            display_name,
            HUDDLE_USERGROUP_ID,
        )
        return

    pending_call_id = state.pending_call_id
    if pending_call_id:
        if pending_call_id == call_id:

            state.queue_pending_participant(user_id, display_name)
            logger.info(
                "Queued %s as pending participant for call_id=%s",
                display_name,
                call_id,
            )
        else:
            logger.debug(
                "Ignoring huddle join by %s — different pending call_id (%s != %s)",
                display_name,
                call_id,
                pending_call_id,
            )
        return

    _send_confirmation_dm(client, user_id, display_name, call_id)


def _handle_huddle_leave(client, user_id: str, display_name: str) -> None:
    """Handles if someone left the huddle"""

    was_present = state.remove_participant(user_id)

    if not (was_present and state.active):
        return

    try:
        client.chat_postMessage(
            channel=LOG_CHANNEL_ID,
            text=f"<@{user_id}> left the huddle. ({state.participant_count()} remaining)",
        )
    except Exception:
        logger.exception("Failed to send leave message")

    logger.info(
        "%s left the huddle (%d remaining)", display_name, state.participant_count()
    )

    if state.participant_count() == 0:
        state.schedule_end(lambda: end_huddle_session(client))


def end_huddle_session(client) -> None:
    """ Ending everything if the huddle ended"""

    if not state.active:
        return

    counts = state.get_review_counts()
    start = state.start_time
    elapsed = datetime.now(timezone.utc) - start if start else None

    hours, remainder = divmod(int(elapsed.total_seconds()), 3600) if elapsed else (0, 0)
    minutes, _ = divmod(remainder, 60)
    elapsed_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    total_reviews = sum(counts.values())

    sorted_reviewers = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    summary_lines = [
        format_reviewer_line(rank, sid, cnt)
        for rank, (sid, cnt) in enumerate(sorted_reviewers, 1)
    ]
    if not summary_lines:
        summary_lines.append("_No reviews were completed this time :sad-yeehaw:_")

    try:
        client.chat_postMessage(
            channel=LOG_CHANNEL_ID,
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "The Huddle Ended!",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"The huddle ran for *{elapsed_str}* with "
                            f"*{total_reviews}* total review{'s' if total_reviews != 1 else ''}.\n\n"
                            f"*Final Standings:*\n" + "\n".join(summary_lines)
                        ),
                    },
                },
            ],
            text=f"🏁 Review Huddle Ended! {total_reviews} reviews in {elapsed_str}.",
        )
    except Exception:
        logger.exception("Failed to send huddle end summary")

    state.end_session()
    logger.info("Huddle session ended")


def handle_approve_huddle(ack, body, client) -> None:
    """When an admin approves a huddle"""
    ack()

    call_id = body["actions"][0].get("value", "")
    pending_call_id, _, dm_ts = state.get_pending()

    if pending_call_id != call_id:
        logger.warning(
            "Approve clicked for call_id=%s but pending is %s — stale button?",
            call_id,
            pending_call_id,
        )
        return

    try:
        dm_channel = body["channel"]["id"]
        client.chat_update(
            channel=dm_channel,
            ts=dm_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "✅ Huddle approved!",
                    },
                },
            ],
            text="Huddle approved!",
        )
    except Exception:
        logger.exception("Failed to update confirmation DM")

    _start_approved_session(client, call_id)


def handle_ignore_huddle(ack, body, client) -> None:
    """When an admin ignores a huddle"""
    ack()

    call_id = body["actions"][0].get("value", "")
    pending_call_id, _, dm_ts = state.get_pending()

    if pending_call_id != call_id:
        logger.warning(
            "Ignore clicked for call_id=%s but pending is %s — stale button?",
            call_id,
            pending_call_id,
        )
        return

    state.clear_pending()


    try:
        dm_channel = body["channel"]["id"]
        client.chat_update(
            channel=dm_channel,
            ts=dm_ts,
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "❌ *Huddle ignored.* This huddle will not be tracked.",
                    },
                },
            ],
            text="Huddle ignored.",
        )
    except Exception:
        logger.exception("Failed to update confirmation DM")

    logger.info("Huddle ignored (call_id=%s)", call_id)


def handle_subteam_members_changed(event: dict, client) -> None:

    event_ts = event.get("event_ts", "")
    if event_ts in _seen_events:
        logger.debug("skip a duplicate (event_ts=%s)", event_ts)
        return

    _seen_events[event_ts] = None
    if len(_seen_events) > _SEEN_EVENTS_MAX:
        _seen_events.popitem(last=False)

    subteam_id = event.get("subteam_id", "")
    if subteam_id != HUDDLE_USERGROUP_ID:
        return

    added = event.get("added_users", [])
    removed = event.get("removed_users", [])

    for uid in added:
        try:
            client.chat_postMessage(
                channel=LOG_CHANNEL_ID,
                text=f"New shipwright, <@{uid}> :)",
            )
        except Exception:
            logger.exception("Failed to send welcome message for %s", uid)

    for uid in removed:
        try:
            client.chat_postMessage(
                channel=LOG_CHANNEL_ID,
                text=f"<@{uid}> is no longer a Shipwright :sad-yeehaw:",
            )
        except Exception:
            logger.exception("Failed to send farewell message for %s", uid)

    if added or removed:
        logger.info(
            "Shipwrights membership change: +%d joined, -%d left",
            len(added),
            len(removed),
        )


def register(app: App) -> None:

    app.event("user_huddle_changed")(handle_huddle_changed)
    app.event("subteam_members_changed")(handle_subteam_members_changed)

    app.action("approve_huddle")(handle_approve_huddle)
    app.action("ignore_huddle")(handle_ignore_huddle)

    @app.event("message")
    def _ack_messages(body):

        pass
