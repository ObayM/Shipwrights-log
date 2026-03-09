from __future__ import annotations

import time

from config import POLL_INTERVAL, LEADERBOARD_INTERVAL, logger
from state import state
from api import fetch_certs
from slack_handlers import _announce_review, _announce_new_queue_project
from leaderboard import post_or_update_leaderboard


def poll_reviews_loop(client) -> None:
    """
    Polls the sw-api for new reviewed certs using the since_reviewed parameter
    Each poll fetches certs reviewed after our last known timestamp :)
    """
    logger.info("polling thread started")
    last_reviewed_at: str | None = None

    while True:
        try:
            if state.active and state.start_time:
                if last_reviewed_at is None:
                    last_reviewed_at = state.start_time.isoformat()

                reviewed = fetch_certs(
                    since_reviewed=last_reviewed_at,
                    sort="reviewCompletedAt",
                    limit=50,
                )

                if reviewed:
                    logger.info(
                        "%d newly reviewed cert(s) since %s",
                        len(reviewed),
                        last_reviewed_at,
                    )

                for cert in reviewed:
                    cert_id = cert.get("id")
                    if cert_id is None:
                        continue

                    if state.has_seen_cert(cert_id):
                        continue

                    state.mark_cert_seen(cert_id)

                    reviewer = cert.get("reviewer")
                    if not reviewer:
                        continue

                    reviewer_slack_id = reviewer.get("slackId")
                    if not reviewer_slack_id:
                        continue

                    if not state.is_participant(reviewer_slack_id):
                        continue

                    state.record_review(reviewer_slack_id)
                    _announce_review(client, cert, reviewer_slack_id)
                    logger.info(
                        "Review by %s: %s -> %s",
                        reviewer.get("username", reviewer_slack_id),
                        cert.get("projectName"),
                        cert.get("status"),
                    )

                if reviewed:
                    latest = max(
                        (c["reviewCompletedAt"] for c in reviewed if c.get("reviewCompletedAt")),
                        default=None,
                    )
                    if latest:
                        last_reviewed_at = latest

            else:
                last_reviewed_at = None

        except Exception:
            logger.exception("Error in review polling loop")

        time.sleep(POLL_INTERVAL)


def leaderboard_loop(client) -> None:
    """update the leaderboard message """
    
    logger.info("Leaderboard update thread started")
    while True:
        try:
            if state.active:
                post_or_update_leaderboard(client)
        except Exception:
            logger.exception("Error in leaderboard loop")

        time.sleep(LEADERBOARD_INTERVAL)


def poll_queue_loop(client) -> None:


    logger.info("Queue polling thread started")

    while True:
        try:
            pending = fetch_certs(status="pending", limit=50)

            if not state.queue_seeded:

                existing_ids = {
                    p["id"] for p in pending if p.get("id") is not None
                }
                state.seed_queue_ids(existing_ids)
                logger.info(
                    "Seeded queue tracker with %d existing project(s)",
                    len(existing_ids),
                )
            else:
                for project in pending:
                    pid = project.get("id")
                    if pid is None:
                        continue
                    if state.has_seen_queue_project(pid):
                        continue

                    state.mark_queue_project_seen(pid)
                    _announce_new_queue_project(client, project)
                    logger.info(
                        "Announced new queue project: %s (id=%s)",
                        project.get("projectName"),
                        pid,
                    )

        except Exception:
            logger.exception("Error in queue polling loop")

        time.sleep(POLL_INTERVAL)
