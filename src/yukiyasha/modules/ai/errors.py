"""Expected errors of the AI module. Messages are Russian: they are shown to the user."""


class AiError(Exception):
    """Base class for expected AI-module errors."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AiNotConfiguredError(AiError):
    """No usable provider settings (address, model, key)."""


class AiBusyError(AiError):
    """Too many requests are being processed at once."""


class MessageRejectedError(AiError):
    """The user's message is empty or too long."""


class ConversationNotFoundError(AiError):
    """The conversation id does not exist."""


class ProviderError(AiError):
    """The provider could not be reached or refused the request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
