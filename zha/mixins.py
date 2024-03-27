"""Mixin classes for Zigbee Home Automation."""

import logging
from typing import Any


class LogMixin:
    """Log helper."""

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log with level."""
        raise NotImplementedError

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Debug level log."""
        return self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Info level log."""
        return self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Warning method log."""
        return self.log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Error level log."""
        return self.log(logging.ERROR, msg, *args, **kwargs)
