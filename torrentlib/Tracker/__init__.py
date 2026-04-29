"""
BitTorrent Tracker Utilities

A Python library for checking tracker availability and querying tracker information.
"""

from .Check import Check
from .Query import Query
from ..Torrent import TorrentStatus

__author__ = "JackyHe398"
__description__ = "BitTorrent tracker utilities for checking availability and querying"

# Define what gets imported with "from  torrentlib import *"
__all__ = [
    "TorrentStatus",
    "Query",
    "Check",
]
