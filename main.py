from __future__ import annotations

import threading

from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, logger
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

import slack_handlers
from threads import poll_reviews_loop, leaderboard_loop, poll_queue_loop

app = App(token=SLACK_BOT_TOKEN)
slack_handlers.register(app)


def main() -> None:

    review_thread = threading.Thread(
        target=poll_reviews_loop,
        args=(app.client,),
        daemon=True,
    )
    review_thread.start()

    leaderboard_thread = threading.Thread(
        target=leaderboard_loop,
        args=(app.client,),
        daemon=True,
    )
    leaderboard_thread.start()

    queue_thread = threading.Thread(
        target=poll_queue_loop,
        args=(app.client,),
        daemon=True,
    )
    queue_thread.start()

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    logger.info("⚡ Review Huddle Bot is running!")
    handler.start()


if __name__ == "__main__":
    main()
