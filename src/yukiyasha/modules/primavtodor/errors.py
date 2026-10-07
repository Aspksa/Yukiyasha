"""Expected errors of the Примавтодор module."""


class PrimavtodorError(Exception):
    """Base class for expected module-level errors."""


class UnknownSectionError(PrimavtodorError):
    """Raised when a section id does not exist."""


class InvalidDocumentNameError(PrimavtodorError):
    """Raised when a document name is not a single, plain file name."""


class UnknownEntityError(PrimavtodorError):
    """Raised when a record kind does not exist."""


class RecordNotFoundError(PrimavtodorError):
    """Raised when a record id does not exist."""


class RecordValidationError(PrimavtodorError):
    """Raised when submitted values break a schema or relation rule.

    ``fields`` maps a field name to a Russian, user-facing message.
    """

    def __init__(self, fields: dict[str, str], message: str = "Проверьте поля формы") -> None:
        super().__init__(message)
        self.fields = fields
        self.message = message


class RecordInUseError(PrimavtodorError):
    """Raised when a record cannot be deleted because other records reference it."""

    def __init__(self, message: str, references: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.references = references
