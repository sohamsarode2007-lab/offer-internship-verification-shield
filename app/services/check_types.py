"""Shared shape of one check's result."""
from typing import Optional, TypedDict


class CheckDict(TypedDict, total=False):
    """One check's result as the checks produce it and the scorer reads it (each check may add its own keys)."""
    check_name: str
    status: str
    score: Optional[int]
    details: Optional[str]
    explanation: Optional[str]
