from __future__ import annotations

import time
from datetime import datetime, timezone

from config import LOG_CHANNEL_ID, logger
from state import state


def format_reviewer_line(rank: int, slack_id: str, count: int) -> str:
    medal = {1: ":tw_first_place_medal:", 2: ":tw_second_place_medal:", 3: ":tw_third_place_medal:"}.get(rank, f"#{rank}")
    plural = "s" if count != 1 else ""
    return f"{medal}  <@{slack_id}> - {count} review{plural}"


def build_leaderboard_blocks() -> list[dict]:

    counts = state.get_review_counts()
    participants = state.get_participants()
    start = state.start_time

    if not start:
        return []

    elapsed = datetime.now(timezone.utc) - start
    hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    elapsed_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    sorted_reviewers = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    lines = [
        format_reviewer_line(rank, sid, cnt)
        for rank, (sid, cnt) in enumerate(sorted_reviewers, 1)
    ]

    if not lines:
        lines.append("_No reviews yet - get cracking!_")

    leaderboard_text = "\n".join(lines)

    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Review Huddle Leaderboard",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"⏱️ Huddle running for *{elapsed_str}*"
                        f"  -  *{len(participants)}* in huddle"
                    ),
                },
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": leaderboard_text},
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Last updated <!date^{int(time.time())}^{{time}}|now>_",
                },
            ],
        },
    ]


def post_or_update_leaderboard(client) -> None:
    """Post a new leaderboard message or edit the existing one."""
    if not state.active:
        return

    blocks = build_leaderboard_blocks()
    if not blocks:
        return

    try:
        ts = state.leaderboard_ts
        if ts:
            client.chat_update(
                channel=LOG_CHANNEL_ID,
                ts=ts,
                blocks=blocks,
                text="Review Huddle Leaderboard",
            )
            logger.info("Updated leaderboard message")
        else:
            resp = client.chat_postMessage(
                channel=LOG_CHANNEL_ID,
                blocks=blocks,
                text="Review Huddle Leaderboard",
            )
            state.leaderboard_ts = resp["ts"]
            logger.info("Posted new leaderboard message")
    except Exception:
        logger.exception("Failed to post/update leaderboard")
