from __future__ import annotations

from datetime import datetime, timezone
from config import LOG_CHANNEL_ID, HUDDLE_USERGROUP_ID, logger
from api import fetch_certs

def post_daily_queue_stats(client) -> None:

    logger.info("working on the daily queue stats")
    
    try:
        pending = fetch_certs(status="pending", limit=200)
    except Exception:
        logger.exception("Failed to fetch pending certs for daily stats")
        return

    total_pending = len(pending)
    overdue_projects = []
    now = datetime.now(timezone.utc)

    for p in pending:
        created_at = p.get("createdAt")
        if not created_at:
            continue
            
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            days_waiting = (now - dt).days
            if days_waiting >= 5:
                p["days_waiting"] = days_waiting
                overdue_projects.append(p)
        except Exception:
            logger.warning("Could not parse createdAt date for project %s: %s", p.get("id"), created_at)

    overdue_count = len(overdue_projects)
    
    overdue_projects.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
    featured_overdue = overdue_projects[:4]

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Daily Queue Stats"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"Hey, Team! Here is the current state of our queue:\n"
                    f"- *{total_pending}* projects currently pending.\n"
                    f"- *{overdue_count}* projects have entered the *5d late era* (>= 5 days waiting)."
                ),
            },
        },
    ]

    if featured_overdue:
        featured_text = "Some projects you need to look at:\n"
        for p in featured_overdue:
            name = p.get("projectName", "Unnamed Project")
            p_type = p.get("projectType", "Project")
            p_id = p.get("id")
            days = p.get("days_waiting", 4)
            dash_url = f"https://review.hackclub.com/admin/ship_certifications/{p_id}/edit" if p_id else "#"
            featured_text += f"• <{dash_url}|{name}> (`{p_type}`)\n"
        
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": featured_text}
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"cc <!subteam^{HUDDLE_USERGROUP_ID}>"}]
    })

    try:
        client.chat_postMessage(
            channel=LOG_CHANNEL_ID,
            blocks=blocks,
            text=f"Daily Queue Stats: {total_pending} pending, {overdue_count} overdue.",
        )
        logger.info("Posted daily queue stats to %s", LOG_CHANNEL_ID)
    except Exception:
        logger.exception("Failed to post daily queue stats to Slack")
