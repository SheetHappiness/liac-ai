"""Errors shared by context projection and its callers."""


class ContextBudgetExceeded(ValueError):
    """The latest input exceeds the context budget."""
