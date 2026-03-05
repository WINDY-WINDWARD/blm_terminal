"""
NSE India Client using nsepython library for fetching and caching data from NSE India APIs.
"""
import asyncio
import logging
import time
from typing import Any
import nsepython

from app.config import settings

logger = logging.getLogger(__name__)


class NSEClient:
    """Singleton async client nsepython library for fetching data from NSE India APIs with built-in caching and session management."""

    def
