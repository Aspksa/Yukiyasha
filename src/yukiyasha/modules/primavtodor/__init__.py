"""Примавтодор module."""

from yukiyasha.modules.primavtodor.errors import (
    InvalidDocumentNameError,
    PrimavtodorError,
    PrintNotAvailableError,
    RecordInUseError,
    RecordNotFoundError,
    RecordValidationError,
    UnknownEntityError,
    UnknownSectionError,
)
from yukiyasha.modules.primavtodor.module import PRIMAVTODOR_MANIFEST, PrimavtodorModule
from yukiyasha.modules.primavtodor.sections import (
    PRIMAVTODOR_DIR,
    SECTIONS,
    SECTIONS_BY_ID,
    Section,
)

__all__ = [
    "PRIMAVTODOR_DIR",
    "PRIMAVTODOR_MANIFEST",
    "SECTIONS",
    "SECTIONS_BY_ID",
    "InvalidDocumentNameError",
    "PrimavtodorError",
    "PrimavtodorModule",
    "PrintNotAvailableError",
    "RecordInUseError",
    "RecordNotFoundError",
    "RecordValidationError",
    "Section",
    "UnknownEntityError",
    "UnknownSectionError",
]
