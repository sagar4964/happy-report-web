from dataclasses import dataclass


class AIError(Exception):
    """An AI problem. user_message is safe to show to staff (no secrets)."""

    def __init__(self, user_message, code="error"):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code


@dataclass
class AIResult:
    text: str
    model: str
