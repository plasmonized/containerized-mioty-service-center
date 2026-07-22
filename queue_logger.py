import asyncio
import logging
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class QueueLogger:
    def __init__(self, queue_name: str, queue_instance: asyncio.Queue):
        self.queue_name = queue_name
        self.queue = queue_instance
        self.original_put = queue_instance.put
        self.original_get = queue_instance.get
        self.daily_counter = 1  # Daily counter that resets
        self.last_reset_date = datetime.now().date()
        self.stats: dict[str, int | float | None] = {
            "put_count": 0,
            "get_count": 0,
            "current_size": 0,
            "max_size_seen": 0,
            "last_put_time": None,
            "last_get_time": None,
            "total_items_processed": 0,
        }

        # Monkey patch the queue methods
        queue_instance.put = self._logged_put  # type: ignore[method-assign]
        queue_instance.get = self._logged_get  # type: ignore[method-assign]

        logger.info(
            f"🔍 Queue Logger initialized for '{queue_name}' (Daily Counter: {self.daily_counter})"
        )
        logger.info(
            f"   ✅ Queue '{queue_name}' logging enabled (Daily Counter: {self.daily_counter})"
        )

    async def _logged_put(self, item: Any) -> None:
        """Logged version of queue.put()"""
        self._check_daily_reset()
        self.stats["put_count"] = (self.stats["put_count"] or 0) + 1
        self.stats["last_put_time"] = time.time()
        self.stats["current_size"] = self.queue.qsize() + 1
        max_val = self.stats["max_size_seen"]
        cur_val = self.stats["current_size"]
        max_seen = int(max_val) if max_val is not None else 0
        cur_size = int(cur_val) if cur_val is not None else 0
        self.stats["max_size_seen"] = max(max_seen, cur_size)

        logger.debug(f"📤 [{self.queue_name}] PUT #{self.stats['put_count']}")
        logger.debug(f"   Queue Daily Counter: {self.daily_counter}")
        logger.debug(f"   New size: {self.stats['current_size']}")
        logger.debug(f"   Item type: {type(item).__name__}")
        if isinstance(item, dict):
            logger.debug(f"   Item keys: {list(item.keys())}")

        await self.original_put(item)

    async def _logged_get(self) -> Any:
        """Logged version of queue.get()"""
        self._check_daily_reset()
        item = await self.original_get()

        self.stats["get_count"] = (self.stats["get_count"] or 0) + 1
        self.stats["last_get_time"] = time.time()
        self.stats["current_size"] = self.queue.qsize()
        self.stats["total_items_processed"] = (self.stats["total_items_processed"] or 0) + 1

        logger.debug(f"📥 [{self.queue_name}] GET #{self.stats['get_count']}")
        logger.debug(f"   Queue Daily Counter: {self.daily_counter}")
        logger.debug(f"   New size: {self.stats['current_size']}")
        logger.debug(f"   Item type: {type(item).__name__}")
        if isinstance(item, dict):
            logger.debug(f"   Item keys: {list(item.keys())}")

        return item

    def _check_daily_reset(self) -> None:
        """Check if we need to reset daily counter"""
        current_date = datetime.now().date()
        if current_date > self.last_reset_date:
            old_counter = self.daily_counter
            self.daily_counter = 1
            self.last_reset_date = current_date
            logger.info(f"🔄 DAILY QUEUE COUNTER RESET for '{self.queue_name}'")
            logger.info(f"   Previous Counter: {old_counter}")
            logger.info(f"   New Counter: {self.daily_counter}")
            logger.info(f"   Reset Date: {current_date}")

    def get_stats(self) -> dict[str, Any]:
        """Get queue statistics"""
        return {
            "queue_name": self.queue_name,
            "daily_counter": self.daily_counter,
            "last_reset_date": self.last_reset_date.isoformat(),
            "current_size": self.queue.qsize(),
            **self.stats,
        }

    def log_stats(self) -> None:
        """Log current queue statistics"""
        self._check_daily_reset()
        stats = self.get_stats()
        logger.info(f"📊 Queue Stats for '{self.queue_name}':")
        logger.info(f"   Daily Counter: {stats['daily_counter']}")
        logger.info(f"   Last Reset: {stats['last_reset_date']}")
        logger.info(f"   Current size: {stats['current_size']}")
        logger.info(f"   Put operations: {stats['put_count']}")
        logger.info(f"   Get operations: {stats['get_count']}")
        logger.info(f"   Max size seen: {stats['max_size_seen']}")
        logger.info(f"   Total processed: {stats['total_items_processed']}")


def setup_queue_logging(queues: dict[str, asyncio.Queue]) -> dict[str, QueueLogger]:
    """Setup logging for multiple queues and return loggers"""
    loggers = {}

    logger.info("🔍 Setting up queue logging...")
    logger.info(f"   Number of queues to monitor: {len(queues)}")

    for name, queue in queues.items():
        loggers[name] = QueueLogger(name, queue)
        logger.info(
            f"   ✅ Queue '{name}' logging enabled (Daily Counter: {loggers[name].daily_counter})"
        )

    return loggers


def log_all_queue_stats(queue_loggers: dict[str, QueueLogger]) -> None:
    """Log statistics for all monitored queues"""
    logger.info("=" * 60)
    logger.info("📊 COMPREHENSIVE QUEUE STATISTICS")
    logger.info("=" * 60)

    for name, queue_logger in queue_loggers.items():
        queue_logger.log_stats()
        logger.info("-" * 40)

    # Check daily counter status
    logger.info("🔄 Daily Counter Summary:")
    for name, queue_logger in queue_loggers.items():
        stats = queue_logger.get_stats()
        logger.info(
            f"   {name}: Daily Counter {stats['daily_counter']} (Reset: {stats['last_reset_date']})"
        )

    logger.info("=" * 60)
