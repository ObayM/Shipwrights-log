from __future__ import annotations

import time

from config import POLL_INTERVAL, LEADERBOARD_INTERVAL, logger
from state import state
from api import fetch_certs
from slack_handlers import _announce_review
from leaderboard import post_or_update_leaderboard


def poll_reviews_loop(client) -> None:
    """
    This just polls the certs fromt the sw-api, it's not the best as I need to do some edits for the sw-api, but it works for now
    It caches the pending certs & once a cert disappear from the pending, we then look the approved/rejected list to get the reviewer info
    
    """
    # Will be refactored later
    logger.info("polling thread started")
    prev_pending_ids: set[int] = set()

    while True:
        try:
            if state.active and state.start_time:
                current_pending = fetch_certs(status="pending")
                current_pending_ids = {
                    c["id"] for c in current_pending if "id" in c
                }

                if prev_pending_ids:

                    disappeared_ids = prev_pending_ids - current_pending_ids

                    if disappeared_ids:
                        logger.info(
                            "%d cert(s) left pending: %s",
                            len(disappeared_ids),
                            disappeared_ids,
                        )


                        reviewed = fetch_certs(
                            status="approved", limit=50
                        ) + fetch_certs(status="rejected", limit=50)
                        reviewed_by_id = {
                            c["id"]: c for c in reviewed if "id" in c
                        }

                        for cert_id in disappeared_ids:
                            if state.has_seen_cert(cert_id):
                                continue

                            cert = reviewed_by_id.get(cert_id)
                            if not cert:
                                state.mark_cert_seen(cert_id)
                                continue

                            reviewer = cert.get("reviewer")
                            if not reviewer:
                                state.mark_cert_seen(cert_id)
                                continue

                            reviewer_slack_id = reviewer.get("slackId")
                            if not reviewer_slack_id:
                                state.mark_cert_seen(cert_id)
                                continue


                            if not state.is_participant(reviewer_slack_id):
                                state.mark_cert_seen(cert_id)
                                continue

                            state.mark_cert_seen(cert_id)
                            state.record_review(reviewer_slack_id)
                            _announce_review(client, cert, reviewer_slack_id)
                            logger.info(
                                "Review by %s: %s -> %s",
                                reviewer.get("username", reviewer_slack_id),
                                cert.get("projectName"),
                                cert.get("status"),
                            )


                prev_pending_ids = current_pending_ids
                logger.debug(
                    "Tracking %d pending certs", len(current_pending_ids)
                )

            else:

                prev_pending_ids = set()

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
