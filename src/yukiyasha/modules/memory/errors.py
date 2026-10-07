"""Memory module domain errors."""


class MemoryError(Exception):
    """Base error for long-term assistant memory."""


class MemoryValidationError(MemoryError):
    """Raised when a memory item is invalid."""


class MemoryNotFoundError(MemoryError):
    """Raised when a memory item does not exist."""


class MemoryLimitError(MemoryError):
    """Raised when the memory store reached its configured limit."""
