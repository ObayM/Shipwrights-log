from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config import HUDDLE_CHANNEL_ID, LOG_CHANNEL_ID, REDACTED_SENTINEL, logger
from state import state
from leaderboard import format_reviewer_line

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




def handle_huddle_changed(event: dict, client) -> None:
    """Just detect when someone join/leave the huddle"""

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
    if not state.active:

        if not state.is_channel_member(client, user_id, HUDDLE_CHANNEL_ID):
            logger.debug(
                "Ignoring huddle join by %s — not a member of target channel %s",
                display_name,
                HUDDLE_CHANNEL_ID,
            )
            return


        state.start_session(call_id)
        state.add_participant(user_id, display_name)
        logger.info(
            "Huddle session started by %s (call_id=%s)", display_name, call_id
        )


        try:
            start_time = state.start_time
            start_ts = int(start_time.timestamp()) if start_time else 0
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

        try:
            client.chat_postMessage(
                channel=LOG_CHANNEL_ID,
                text=f"<@{user_id}> joined the huddle! ({state.participant_count()} in huddle)",
            )
        except Exception:
            logger.exception("Failed to send join message")

    else:

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


def register(app: App) -> None:
    
    app.event("user_huddle_changed")(handle_huddle_changed)

    @app.event("message")
    def _ack_messages(body):

        pass
