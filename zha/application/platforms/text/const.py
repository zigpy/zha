"""Constants for the text platform."""

from enum import StrEnum

# Home Assistant's `text` entities can't hold more characters than a state string
MAX_LENGTH_STATE_STATE = 255


class TextMode(StrEnum):
    """How the frontend shows the text input."""

    TEXT = "text"
    PASSWORD = "password"
