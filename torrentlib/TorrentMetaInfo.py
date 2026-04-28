import hashlib
from pathlib import Path
from typing import Any, Optional

import torrent_parser as tp


def _count_pieces(pieces: Any) -> Optional[int]:
    """Count torrent pieces across parser output shapes."""
    if pieces is None:
        return None
    if isinstance(pieces, list):
        return len(pieces)
    if isinstance(pieces, bytes):
        return len(pieces) // 20
    if isinstance(pieces, str):
        return len(pieces) // 40
    return None


class TorrentMetaInfo:
    def __init__(self, data: dict[bytes, Any]):
        self.data = data
        self._info_bytes: Optional[bytes] = None
        self._info_hash: Optional[str] = None

        if b"info_hash" in self.data:
            self._info_hash = self.data[b"info_hash"]
        self.refresh()

    @classmethod
    def from_file(cls, filename: str) -> "TorrentMetaInfo":
        data = tp.parse_torrent_file(filename)
        if not isinstance(data, dict):
            raise ValueError(f"Failed to parse torrent file: {filename}")
        return cls(data)

    # region - property
    @property
    def has_info(self) -> bool:
        return b"info" in self.data and isinstance(self.data[b"info"], dict)

    @property
    def info(self) -> Optional[dict[bytes, Any]]:
        info = self.data.get(b"info")
        return info if isinstance(info, dict) else None

    @property
    def info_hash(self) -> str:
        return self._info_hash or ""

    @property
    def info_bytes(self) -> Optional[bytes]:
        return self._info_bytes

    @property
    def name(self) -> Optional[str]:
        if self.info is not None:
            return self.info.get(b"name")
        return self.data.get(b"name")

    @property
    def piece_length(self) -> Optional[int]:
        if self.info is not None:
            return self.info.get(b"piece length")
        return self.data.get(b"piece length")

    @property
    def num_pieces(self) -> Optional[int]:
        if self.info is not None:
            pieces = self.info.get(b"pieces")
            if pieces is not None:
                return _count_pieces(pieces)
        return self.data.get(b"num_pieces")

    @property
    def total_size(self) -> int:
        if self.info is not None:
            files = self.info.get(b"files")
            if isinstance(files, list): # multiple files
                total_size = 0
                for file_info in files:
                    if not isinstance(file_info, dict):
                        raise ValueError("Torrent file entry is malformed")
                    total_size += file_info.get(b"length", 0)
                    
                return total_size
            else: # single file
                return self.info.get(b"length", 0)
        return self.data.get(b"total_size", 0)
    # endregion

    def _is_refreshable(self) -> bool:
        if self.info is None:
            return False
        
        mandatory_key_exist = all(key in self.info for key in (b"name", b"piece length", b"pieces"))
        file_info_exist = b"length" in self.info or b"files" in self.info
        return (mandatory_key_exist and file_info_exist)

    def refresh(self) -> None:
        if not self._is_refreshable():
            return

        import bencodepy

        assert self.info is not None
        info_bytes = bencodepy.encode(self.info)  # type: ignore[arg-type]
        self._info_bytes = info_bytes
        self._info_hash = hashlib.sha1(info_bytes).hexdigest()
        self.data[b"info_hash"] = self._info_hash

    def _exportable_data(self) -> dict[bytes, Any]:
        return {
            key: value
            for key, value in self.data.items()
            if key not in (b"info_hash", b"name", b"piece length", b"num_pieces", b"total_size")
        }

    def update_from_info_bytes(self, metadata: bytes) -> None:
        """
        Update metainfo from bencoded ``info`` dictionary bytes.

        Args:
            metadata: Bencoded 'info' dictionary bytes

        Raises:
            ValueError: If the decoded info dictionary is malformed or the hash mismatches.
        """
        import bencodepy

        computed_hash = hashlib.sha1(metadata).hexdigest()
        if self.info_hash and computed_hash != self.info_hash:
            raise ValueError(f"Metadata hash mismatch: expected {self.info_hash}, got {computed_hash}")

        info: dict[bytes, Any] = bencodepy.decode(metadata)  # type: ignore
        if not isinstance(info, dict):
            raise ValueError("Torrent metadata info dictionary is malformed")

        self.data[b"info"] = info
        self.refresh()

    def to_bytes(self) -> bytes:
        import bencodepy

        exportable_data = self._exportable_data()
        if b"info" not in exportable_data:
            raise ValueError("Cannot export metainfo without an info dictionary")
        return bencodepy.encode(exportable_data)  # type: ignore[arg-type]

    def to_file(self, path: str) -> None:
        Path(path).write_bytes(self.to_bytes())
