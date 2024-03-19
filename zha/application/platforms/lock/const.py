"""Constants for the lock platform."""

from typing import Final

STATE_LOCKED: Final[str] = "locked"
STATE_UNLOCKED: Final[str] = "unlocked"
STATE_LOCKING: Final[str] = "locking"
STATE_UNLOCKING: Final[str] = "unlocking"
STATE_JAMMED: Final[str] = "jammed"
# The first state is Zigbee 'Not fully locked'
STATE_LIST: Final[list[str]] = [STATE_UNLOCKED, STATE_LOCKED, STATE_UNLOCKED]
VALUE_TO_STATE: Final = dict(enumerate(STATE_LIST))
