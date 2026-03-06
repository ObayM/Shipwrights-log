from __future__ import annotations

import time
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config import logger, CHANNEL_MEMBER_CACHE_TTL

if TYPE_CHECKING:
    from slack_sdk import WebClient


class HuddleState:

    GRACE_PERIOD = 30

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: bool = False
        self._start_time: datetime | None = None
        self._tracked_call_id: str | None = None
        self._leaderboard_ts: str | None = None
        self._announcement_ts: str | None = None
        self._participants: dict[str, str] = {}
        self._review_counts: dict[str, int] = {}
        self._seen_cert_ids: set[int] = set()
        self._end_timer: threading.Timer | None = None

        self._channel_members: set[str] = set()
        self._channel_members_updated: float = 0.0


    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def start_time(self) -> datetime | None:
        with self._lock:
            return self._start_time

    @property
    def tracked_call_id(self) -> str | None:
        with self._lock:
            return self._tracked_call_id

    @property
    def leaderboard_ts(self) -> str | None:
        with self._lock:
            return self._leaderboard_ts

    @leaderboard_ts.setter
    def leaderboard_ts(self, value: str | None) -> None:
        with self._lock:
            self._leaderboard_ts = value

    @property
    def announcement_ts(self) -> str | None:
        with self._lock:
            return self._announcement_ts

    @announcement_ts.setter
    def announcement_ts(self, value: str | None) -> None:
        with self._lock:
            self._announcement_ts = value


    def add_participant(self, slack_id: str, name: str) -> bool:

        with self._lock:
            if self._end_timer is not None:
                self._end_timer.cancel()
                self._end_timer = None
                logger.info("Cancelled pending huddle end - someone joined :)")

            if slack_id in self._participants:
                return False
            self._participants[slack_id] = name
            return True

    def remove_participant(self, slack_id: str) -> bool:

        with self._lock:
            return self._participants.pop(slack_id, None) is not None

    def is_participant(self, slack_id: str) -> bool:
        with self._lock:
            return slack_id in self._participants

    def get_participants(self) -> dict[str, str]:
        with self._lock:
            return dict(self._participants)

    def participant_count(self) -> int:
        with self._lock:
            return len(self._participants)


    def record_review(self, slack_id: str) -> None:
        with self._lock:
            self._review_counts[slack_id] = self._review_counts.get(slack_id, 0) + 1

    def get_review_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._review_counts)

    def has_seen_cert(self, cert_id: int) -> bool:
        with self._lock:
            return cert_id in self._seen_cert_ids

    def mark_cert_seen(self, cert_id: int) -> None:
        with self._lock:
            self._seen_cert_ids.add(cert_id)


    def is_channel_member(
        self, client: WebClient, user_id: str, channel_id: str
    ) -> bool:
        """if <user_id> in the *channel_id*"""
        
        with self._lock:
            cache_age = time.monotonic() - self._channel_members_updated
            need_refresh = cache_age > CHANNEL_MEMBER_CACHE_TTL or not self._channel_members

        if need_refresh:
            self._refresh_channel_members(client, channel_id)

        with self._lock:
            return user_id in self._channel_members

    def _refresh_channel_members(
        self, client: WebClient, channel_id: str
    ) -> None:

        members: set[str] = set()
        try:
            cursor = None
            while True:
                kwargs: dict = {"channel": channel_id, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = client.conversations_members(**kwargs)
                members.update(resp.get("members", []))
                cursor = resp.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        except Exception:
            logger.exception(
                "Failed to fetch channel members for %s — using stale cache", channel_id
            )
            return  # keep old cache rather than wiping it

        with self._lock:
            self._channel_members = members
            self._channel_members_updated = time.monotonic()
            logger.debug("Refreshed channel member cache: %d members", len(members))



    def start_session(self, call_id: str) -> None:
        with self._lock:
            self._active = True
            self._start_time = datetime.now(timezone.utc)
            self._tracked_call_id = call_id
            self._participants.clear()
            self._review_counts.clear()
            self._seen_cert_ids.clear()
            self._leaderboard_ts = None
            self._announcement_ts = None

    def schedule_end(self, callback) -> None:
        """Schedule session end after grace period.

        *callback* is called with no arguments if the timer fires and
        there are still zero participants.
        """
        with self._lock:
            if self._end_timer is not None:
                self._end_timer.cancel()
            self._end_timer = threading.Timer(
                self.GRACE_PERIOD,
                self._maybe_end_session,
                args=(callback,),
            )
            self._end_timer.daemon = True
            self._end_timer.start()
            logger.info(
                "Huddle empty — will end in %ds unless someone rejoins",
                self.GRACE_PERIOD,
            )

    def _maybe_end_session(self, callback) -> None:
        # We need a grace period :(
        
        with self._lock:
            self._end_timer = None
            if len(self._participants) > 0:
                logger.info(
                    "Grace period passed but someone returned - let's continue"
                )
                return

        callback()

    def end_session(self) -> None:
        with self._lock:
            if self._end_timer is not None:
                self._end_timer.cancel()
                self._end_timer = None
            self._active = False
            self._start_time = None
            self._tracked_call_id = None
            self._participants.clear()
            self._review_counts.clear()
            self._seen_cert_ids.clear()
            self._leaderboard_ts = None
            self._announcement_ts = None



state = HuddleState()
