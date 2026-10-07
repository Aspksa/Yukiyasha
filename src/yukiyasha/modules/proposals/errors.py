"""Proposal workflow domain errors."""


class ProposalError(Exception):
    """Base error for proposal lifecycle failures."""


class ProposalNotFoundError(ProposalError):
    """Raised when a proposal does not exist."""


class ProposalValidationError(ProposalError):
    """Raised when a proposal request is invalid."""


class ProposalStateError(ProposalError):
    """Raised when a proposal cannot transition from its current state."""


class ProposalStaleError(ProposalError):
    """Raised when the target changed after proposal creation."""
