import torrent_parser as tp
import threading
import humanize
from typing import Any, Optional
from enum import Enum


def _parse_torrent_file(filename: str) -> Optional[dict[str, Any]]:
    """
    Parse a .torrent file and convert all bytes to strings/hex for JSON serialization.
    
    Args:
        filename: Path to the .torrent file
        
    Returns:
        Dictionary with all bytes converted to strings (text) or hex (binary data),
        or None if parsing fails
    """
    data_b: dict[str, Any] = tp.parse_torrent_file(filename)
    
    # Convert bytes to strings for JSON serialization
    def bytes_to_str(obj, path=''):
        if isinstance(obj, bytes):
            # These fields contain binary hash/random data, convert to hex
            binary_fields = [
                'pieces', 'hash', 'sha1', 'sha256', 'sha32', 
                'filedata', 'created rd', 'piece layers',
                'root hash', 'pieces root'
            ]
            if any(hash_field in path for hash_field in binary_fields):
                return obj.hex()
            # Try UTF-8 first
            try:
                return obj.decode('utf-8')
            except UnicodeDecodeError:
                # If it's likely binary (many non-printable chars), convert to hex
                if sum(1 for b in obj if b < 32 or b > 126) > len(obj) // 2:
                    return obj.hex()
                # Otherwise fall back to latin-1
                return obj.decode('latin-1')
        elif isinstance(obj, dict):
            return {bytes_to_str(k, path): bytes_to_str(v, f"{path}.{k}") for k, v in obj.items()}
        elif isinstance(obj, list):
            return [bytes_to_str(item, f"{path}[]") for item in obj]
        return obj
    
    data_serializable: dict[str, Any] = bytes_to_str(data_b) # type: ignore
    return data_serializable


class TorrentStatus(Enum):
    COMPLETED = 1
    STARTED = 2
    STOPPED = 3

class Torrent:
    """Represents a torrent instance, encapsulating tracker and metadata information."""
    def __init__(self, info_hash: str,
            total_size: int = 0, left: Optional[int] = None,
            downloaded: int = 0, uploaded: int = 0,
            event: TorrentStatus = TorrentStatus.STARTED,
            name: Optional[str] = None,
            piece_length: Optional[int] = None,
            num_pieces: Optional[int] = None):
        """
        Initialize a Torrent object.

        Args:
            info_hash (str): The unique identifier of the torrent.
            total_size (int): The total size of the torrent in bytes.
            left (int): The number of bytes still needed to complete. Defaults to (total_size - downloaded).
            downloaded (int): The number of bytes downloaded. Defaults to 0.
            uploaded (int): The number of bytes uploaded. Defaults to 0.
            num_want (int|None): The number of peers requested. Defaults to None.
            event (TorrentStatus): The current tracker event. Defaults to TorrentStatus.STARTED.
            name (str|None): The name of the torrent (from 'info' dict). Optional.
            piece_length (int|None): Length of each piece in bytes. Optional.
            num_pieces (int|None): Total number of pieces. Optional.

        Raises:
            ValueError: If total_size is not a positive integer.
        """
        
        # data validation
        assert isinstance(total_size, int) and total_size >= 0, "total_size must be a non-negative integer"
        assert isinstance(downloaded, int) and downloaded >= 0, "downloaded must be a non-negative integer"
        assert isinstance(uploaded, int) and uploaded >= 0, "uploaded must be a non-negative integer"
        assert left is None or (isinstance(left, int) and left >= 0), "left must be a non-negative integer or None"
        
        # Metadata (lightweight, for peer metadata exchange)
        self.info_hash = info_hash
        self.name = name
        self.piece_length = piece_length
        self.num_pieces = num_pieces
        self.total_size = total_size
        
        # Store bencoded 'info' dict only if retrieved from peer
        self.metadata: Optional[bytes] = None
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
    def from_file(cls, filename: str, downloaded: int = 0, uploaded: int = 0, 
                  event: TorrentStatus = TorrentStatus.STARTED) -> 'Torrent':
        """
        Create a Torrent instance from a .torrent file.
        
        Args:
            filename: Path to the .torrent file
            downloaded: Bytes already downloaded (default: 0)
            uploaded: Bytes already uploaded (default: 0)
            event: Initial torrent status (default: STARTED)
            
        Returns:
            Torrent instance with metadata loaded from file
            
        Raises:
            FileNotFoundError: If the torrent file doesn't exist
            ValueError: If the torrent file is invalid or missing required fields
        """
        import bencodepy
        import hashlib
        
        data = _parse_torrent_file(filename)
        if data is None:
            raise ValueError(f"Failed to parse torrent file: {filename}")
        
        info = data.get('info')
        if info is None:
            raise ValueError(f"Torrent file missing 'info' dict: {filename}")
        
        # Extract metadata
        metadata = bencodepy.encode(info)  # type: ignore
        hash_obj = hashlib.sha1()
        hash_obj.update(metadata)
        info_hash = hash_obj.hexdigest()
        
        name = info.get('name')
        piece_length = info.get('piece length')
        pieces_hex = info.get('pieces', '')
        num_pieces = len(pieces_hex) // 40  # Each SHA-1 piece hash is 20 bytes = 40 hex chars
        
        # Calculate total size
        total_size = 0
        if 'files' in info:
            # Multi-file torrent
            for file_info in info['files']:
                total_size += file_info.get('length', 0)
        else:
            # Single-file torrent
            total_size = info.get('length', 0)
        
        # Create instance
        torrent = cls(
            info_hash=info_hash,
            total_size=total_size,
            downloaded=downloaded,
            uploaded=uploaded,
            event=event,
            name=name,
            piece_length=piece_length,
            num_pieces=num_pieces
        )
        
        # Store the bencoded metadata
        torrent.metadata = metadata
        
        return torrent

    # region - helper functio
    def update_uploaded(self, bytes_uploaded: int):
        self.uploaded += bytes_uploaded

    def update_downloaded(self, bytes_downloaded: int):
        self.downloaded += bytes_downloaded
        self.left = max(self.total_size - self.downloaded, 0)

    def set_event(self, event: TorrentStatus):
        self.event = event   
     
    def get_files_info(self) -> Optional[dict[str, dict]]:
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
            
            if self.metadata is None:
                return None
            
            # Parse metadata and build cache
            import bencodepy
            info_dict: dict[bytes, Any] = bencodepy.decode(self.metadata) # type: ignore
            if not isinstance(info_dict, dict):
                raise ValueError("Torrent metadata info dictionary is malformed")
            self._file_cache = {}
            
            if b'files' in info_dict:
                # Multi-file torrent
                for file_info in info_dict[b'files']:
                    if not isinstance(file_info, dict):
                        raise ValueError("Torrent file entry is malformed")
                    if b'hash' in file_info:
                        if b'path' not in file_info or b'length' not in file_info:
                            raise ValueError("Torrent file entry missing required fields")
                        hash_hex = file_info[b'hash'].hex()
                        path = [p.decode('utf-8') for p in file_info[b'path']]
                        self._file_cache[hash_hex] = {
                            'name': path[-1],
                            'length': file_info[b'length'],
                            'path': path
                        }
            else:
                # Single-file torrent
                if b'pieces' in info_dict:
                    if b'name' not in info_dict or b'length' not in info_dict:
                        raise ValueError("Single-file torrent metadata missing required fields")
                    # Use first 32 bytes of pieces hash as file identifier
                    hash_hex = info_dict[b'pieces'][:32].hex()
                    name = info_dict[b'name'].decode('utf-8')
                    self._file_cache[hash_hex] = {
                        'name': name,
                        'length': info_dict[b'length'],
                        'path': [name]
                    }
            
            return self._file_cache
    
    def get_file_by_hash(self, hash_hex: str) -> Optional[dict]:
        """Get file info by hash. Returns None if not found."""
        files = self.get_files_info()
        return files.get(hash_hex) if files else None
    
    def update_from_metadata(self, metadata: bytes):
        """
        Update torrent fields (name, piece_length, num_pieces, total_size) 
        from metadata received from peer. Thread-safe.
        
        Args:
            metadata: Bencoded 'info' dictionary bytes
        """
        with self._lock:
            import bencodepy
            import hashlib
            
            # Verify hash matches
            computed_hash = hashlib.sha1(metadata).hexdigest()
            if computed_hash != self.info_hash:
                raise ValueError(f"Metadata hash mismatch: expected {self.info_hash}, got {computed_hash}")
            
            # Store metadata
            self.metadata = metadata
            
            # Decode and update fields
            info: dict[bytes, Any] = bencodepy.decode(metadata)  # type: ignore
            if not isinstance(info, dict):
                raise ValueError("Metadata info dictionary is malformed")
            
            # Update name if not set
            if self.name is None and b'name' in info:
                self.name = info[b'name'].decode('utf-8')
            
            # Update piece_length if not set
            if self.piece_length is None and b'piece length' in info:
                self.piece_length = info[b'piece length']
            
            # Update num_pieces if not set
            if self.num_pieces is None and b'pieces' in info:
                self.num_pieces = len(info[b'pieces']) // 20
            
            # Recalculate total_size from metadata
            if b'files' in info:
                # Multi-file torrent
                calculated_size = 0
                for file_info in info[b'files']:
                    if not isinstance(file_info, dict) or b'length' not in file_info:
                        raise ValueError("Metadata file entry missing required length")
                    calculated_size += file_info[b'length']
            else:
                # Single-file torrent
                calculated_size = info.get(b'length', 0)
            
            # Update total_size and left
            if calculated_size > 0:
                self.total_size = calculated_size
                self.left = max(self.total_size - self.downloaded, 0)
    # endregion - helper functions
