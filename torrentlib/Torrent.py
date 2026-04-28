import threading
from enum import Enum
from typing import Any, Optional

import humanize

from .TorrentMetaInfo import TorrentMetaInfo


class TorrentStatus(Enum):
    COMPLETED = 1
    STARTED = 2
    STOPPED = 3


class Torrent:
    """Represents a torrent instance, encapsulating tracker and metadata information."""

    def __init__(
        self,
        info_hash: str,
        total_size: int = 0,
        left: Optional[int] = None,
        downloaded: int = 0,
        uploaded: int = 0,
        event: TorrentStatus = TorrentStatus.STARTED,
        name: Optional[str] = None,
        piece_length: Optional[int] = None,
        num_pieces: Optional[int] = None,
    ):
        """
        Initialize a Torrent object.

        Args:
            info_hash (str): The unique identifier of the torrent.
            total_size (int): The total size of the torrent in bytes.
            left (int): The number of bytes still needed to complete. Defaults to
                ``total_size - downloaded``.
            downloaded (int): The number of bytes downloaded. Defaults to 0.
            uploaded (int): The number of bytes uploaded. Defaults to 0.
            event (TorrentStatus): The current tracker event. Defaults to
                TorrentStatus.STARTED.
            name (str | None): Optional torrent name hint stored in metainfo data.
            piece_length (int | None): Optional piece length hint stored in metainfo data.
            num_pieces (int | None): Optional piece count hint stored in metainfo data.

        Raises:
            ValueError: If numeric state is invalid.
        """
        # data validation
        assert isinstance(total_size, int) and total_size >= 0, "total_size must be a non-negative integer"
        assert isinstance(downloaded, int) and downloaded >= 0, "downloaded must be a non-negative integer"
        assert isinstance(uploaded, int) and uploaded >= 0, "uploaded must be a non-negative integer"
        assert left is None or (isinstance(left, int) and left >= 0), "left must be a non-negative integer or None"


        # store incomplete field into metainfo
        metainfo_data: dict[bytes, Any] = {b"info_hash": info_hash}
        if name is not None:
            metainfo_data[b"name"] = name
        if piece_length is not None:
            metainfo_data[b"piece length"] = piece_length
        if num_pieces is not None:
            metainfo_data[b"num_pieces"] = num_pieces
        if total_size > 0:
            metainfo_data[b"total_size"] = total_size
        self.metainfo = TorrentMetaInfo(metainfo_data)

        # File list cache (lazy-loaded when first accessed)
        self._file_cache: Optional[dict[str, dict]] = None  # {hash_hex: {'name': str, 'length': int, 'path': list}}
        
        # Thread safety locks
        self._lock = threading.RLock()  # For metadata and file cache
        self._peers_lock = threading.Lock()  # For peer dictionaries
        
        # Torrent status
        self.uploaded = uploaded
        self.downloaded = downloaded
        cal_left = max(self.total_size - self.downloaded, 0)
        self.left = cal_left if left is None else left
        self.event = event   # Default tracker event
        
        self.peers: dict[tuple[str, int], dict] = {}  # List of (ip, port) tuples
        self.peers6: dict[tuple[str, int], dict] = {} # List of (ip, port) tuples for IPv6
    
    def __str__(self) -> str:
        """"Human-readable string representation of the torrent."""
        
        name = self.name if self.name else "Unknown"
        hash_short = self.info_hash[:16] + "..." if len(self.info_hash) > 16 else self.info_hash
        
        size_str = humanize.naturalsize(self.total_size, binary=True)
        progress = ((self.total_size - self.left) / self.total_size * 100) if self.total_size > 0 else 0
        
        parts = [
            f"Torrent('{name}'",
            f"hash={hash_short}",
            f"size={size_str}",
            f"progress={progress:.1f}%",
            f"peers={len(self.peers)}",
        ]
        
        return ", ".join(parts) + ")"
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (f"Torrent(info_hash='{self.info_hash[:16]}...', "
                f"name={self.name!r}, total_size={self.total_size}, "
                f"downloaded={self.downloaded}, uploaded={self.uploaded})")
        
    @classmethod
    def from_metainfo(
        cls,
        metainfo: TorrentMetaInfo,
        downloaded: int = 0,
        uploaded: int = 0,
        event: TorrentStatus = TorrentStatus.STARTED,
    ) -> "Torrent":
        """
        Create a Torrent instance from an existing TorrentMetaInfo object.
        """
        torrent = cls(
            info_hash=metainfo.info_hash,
            total_size=metainfo.total_size,
            downloaded=downloaded,
            uploaded=uploaded,
            event=event,
            name=metainfo.name,
            piece_length=metainfo.piece_length,
            num_pieces=metainfo.num_pieces,
        )
        torrent.metainfo = metainfo
        return torrent

    @classmethod
    def from_file(
        cls,
        filename: str,
        downloaded: int = 0,
        uploaded: int = 0,
        event: TorrentStatus = TorrentStatus.STARTED,
    ) -> "Torrent":
        """
        Create a Torrent instance from a .torrent file.
        
        Args:
            filename: Path to the .torrent file
            downloaded: Bytes already downloaded (default: 0)
            uploaded: Bytes already uploaded (default: 0)
            event: Initial torrent status (default: STARTED)
            
        Returns:
            Torrent instance with metadata loaded from file
        """
        return cls.from_metainfo(
            TorrentMetaInfo.from_file(filename),
            downloaded=downloaded,
            uploaded=uploaded,
            event=event,
        )

    # region - property
    @property
    def has_metainfo(self) -> bool:
        """Whether full torrent metainfo is currently available."""
        return self.metainfo.has_info

    @property
    def metadata(self) -> Optional[bytes]:
        """Backward-compatible alias for the bencoded info dictionary bytes."""
        return self.metainfo.info_bytes

    @property
    def info_hash(self) -> str:
        return self.metainfo.info_hash

    @property
    def name(self) -> Optional[str]:
        return self.metainfo.name

    @property
    def piece_length(self) -> Optional[int]:
        return self.metainfo.piece_length

    @property
    def num_pieces(self) -> Optional[int]:
        return self.metainfo.num_pieces

    @property
    def total_size(self) -> int:
        return self.metainfo.total_size
    # endregion

    # region - helper function
    def update_uploaded(self, bytes_uploaded: int):
        self.uploaded += bytes_uploaded

    def update_downloaded(self, bytes_downloaded: int):
        self.downloaded += bytes_downloaded
        self.left = max(self.total_size - self.downloaded, 0)

    def set_event(self, event: TorrentStatus):
        self.event = event   
     
    def get_files_info(self) -> Optional[dict[str, dict[str, Any]]]:
        """
        Get file list as {hash_hex: {'name': str, 'length': int, 'path': list}}.
        Uses lazy loading - only parses metadata once, then caches result.
        Thread-safe with double-check locking pattern.
        
        Returns:
            Dict mapping file hash (hex) to file info, or None if metadata not available.
        """
        # Fast path: cache already built
        if self._file_cache is not None:
            return self._file_cache
        
        # Acquire lock for lazy initialization
        with self._lock:
            # Double-check: another thread might have built cache while we waited
            if self._file_cache is not None:
                return self._file_cache
            if not self.metainfo.has_info:
                return None
            
            # Parse metadata and build cache
            info_dict = self.metainfo.info
            assert info_dict is not None
            self._file_cache = {}

            if b"files" in info_dict:
                # Multi-file torrent
                for file_info in info_dict[b"files"]:
                    if not isinstance(file_info, dict):
                        raise ValueError("Torrent file entry is malformed")
                    if b"hash" in file_info:
                        if b"path" not in file_info or b"length" not in file_info:
                            raise ValueError("Torrent file entry missing required fields")
                        hash_hex = file_info[b"hash"].hex()
                        path = [p.decode("utf-8") for p in file_info[b"path"]]
                        self._file_cache[hash_hex] = {
                            "name": path[-1],
                            "length": file_info[b"length"],
                            "path": path,
                        }
            else:
                # Single-file torrent
                if b"pieces" in info_dict:
                    if b"name" not in info_dict or b"length" not in info_dict:
                        raise ValueError("Single-file torrent metadata missing required fields")
                    # Use first 32 bytes of pieces hash as file identifier
                    hash_hex = info_dict[b"pieces"][:32].hex()
                    name = info_dict[b"name"].decode("utf-8")
                    self._file_cache[hash_hex] = {
                        "name": name,
                        "length": info_dict[b"length"],
                        "path": [name],
                    }
            
            return self._file_cache
    
    def get_file_by_hash(self, hash_hex: str) -> Optional[dict]:
        """Get file info by hash. Returns None if not found."""
        files = self.get_files_info()
        return files.get(hash_hex) if files else None
    
    def update_from_metadata(self, metadata: bytes):
        """
        Update torrent metainfo from peer-retrieved bencoded ``info`` bytes.
        Thread-safe.
          
        Args:
            metadata: Bencoded 'info' dictionary bytes
        """
        with self._lock:
            self.metainfo.update_from_info_bytes(metadata)
            self._file_cache = None
            self.left = max(self.total_size - self.downloaded, 0)
    # endregion - helper functions
