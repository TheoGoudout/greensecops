import logging

from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.services.storage.object_store import ensure_bucket

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5  # 5 minutes
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
def init() -> None:
    ensure_bucket()


def main() -> None:
    logger.info("Initializing object storage")
    init()
    logger.info("Object storage finished initializing")


if __name__ == "__main__":
    main()
