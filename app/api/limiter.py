"""
Rate limiting (slowapi), keyed by client IP.

RATE_LIMIT           default 10/min (can be overridden by ENV)\n"""
from slowapi import Limiter
from slowapi.utils import get_remote_address

limiter = Limiter(key_func=get_remote_address)
