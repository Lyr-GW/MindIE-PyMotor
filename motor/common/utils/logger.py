# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Constants for enhanced logging
LOG_MAX_LINE_LENGTH = 1023
LOG_DEFAULT_FORMAT = '%(levelname)s  %(asctime)s  [%(filename)s:%(lineno)d]  %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class ApiAccessFilter(logging.Filter):
    """Suppress uvicorn access logs for specified APIs unless level >= configured level."""

    def __init__(self, api_filters: dict[str, int] = None):
        """
        Args:
            api_filters: dict mapping API paths to minimum log levels.
                        e.g., {"/heartbeat": logging.ERROR, "/register": logging.WARNING}
        """
        super().__init__()
        self.api_filters = api_filters or {}

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if record.name == "uvicorn.access":
            for path, min_level in self.api_filters.items():
                if path in message:
                    return record.levelno >= min_level
        return True



class MaxLengthFormatter(logging.Formatter):
    """
    Formatter that limits log message length to prevent performance issues.
    """

    def __init__(self, fmt=None, max_length=LOG_MAX_LINE_LENGTH, datefmt=None, style='%'):
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.max_length = max_length

    def format(self, record):
        msg = super().format(record)
        # Escape special characters and limit length
        msg = repr(msg)[1:-1]  # Remove quotes added by repr()
        if len(msg) > self.max_length:
            return msg[:self.max_length] + '...'
        return msg


def get_logger(name: str = __name__, log_file: Optional[str] = None, level: int = logging.INFO):
    """
    Get or create a logger with enhanced capabilities.

    Args:
        name: Logger name (usually __name__)
        log_file: Optional file path for file logging
        level: Logging level (default: INFO)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(level)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        formatter = MaxLengthFormatter(LOG_DEFAULT_FORMAT, datefmt=LOG_DATE_FORMAT)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler (optional)
        if log_file:
            # Ensure log directory exists
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                try:
                    Path(log_dir).mkdir(parents=True, exist_ok=True)
                except Exception:
                    # If directory creation fails, skip file logging
                    pass
            else:
                try:
                    file_handler = logging.FileHandler(log_file, encoding='utf-8')
                    file_handler.setLevel(level)
                    file_handler.setFormatter(formatter)
                    logger.addHandler(file_handler)
                except Exception:
                    # If file logging fails, continue with console only
                    pass

    return logger


class ApiAccessFilter(logging.Filter):
    """Suppress uvicorn access logs for specified APIs unless level >= configured level."""

    def __init__(self, api_filters: dict[str, int] = None):
        """
        Args:
            api_filters: dict mapping API paths to minimum log levels.
                        e.g., {"/heartbeat": logging.ERROR, "/register": logging.WARNING}
        """
        super().__init__()
        self.api_filters = api_filters or {}

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if record.name == "uvicorn.access":
            for path, min_level in self.api_filters.items():
                if path in message:
                    return record.levelno >= min_level
        return True