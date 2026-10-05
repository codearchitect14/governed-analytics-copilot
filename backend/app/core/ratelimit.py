"""Rate limiting (slowapi). Keyed by client address. Login limits are read from settings."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[], headers_enabled=True)
