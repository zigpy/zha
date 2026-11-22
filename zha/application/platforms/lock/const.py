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

# Status values of the DoorLock command responses (ZCL R8 7.3.2.16): lock, unlock,
# clear PIN code and set user status answer pass/fail, set PIN code also uses 2 and 3
RESPONSE_STATUS_REASONS: Final[dict[int, str]] = {
    1: "general failure",
    2: "memory full",
    3: "duplicate code",
}
