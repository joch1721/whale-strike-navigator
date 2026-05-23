"""
Logging setup using loguru. Import and call setup_logging() at the top
of any script or the FastAPI startup event.
"""

import sys
from loguru import logger


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        "logs/navigator.log",
        level="DEBUG",
        rotation="10 MB",
        retention="14 days",
        compression="zip",
    )


# Re-export so callers only need one import
__all__ = ["logger", "setup_logging"]
