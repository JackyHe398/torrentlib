import hashlib
import bencodepy
from pathlib import Path
from typing import Any, Optional


def _decode_text(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


class TorrentMetaInfo:
    def __init__(self, data: dict[bytes, Any]):
        self.data = data
        self.data.setdefault(b"info", {})
        if not isinstance(self.data[b"info"], dict):
            raise ValueError("b'info' must be a dictionary when present")

        if self._is_refreshable():
            self.refresh()
        elif b"info_hash" not in data:
            raise ValueError("Need either b'info' or b'info_hash' in the given data")

    @classmethod
    def from_file(cls, filename: str) -> "TorrentMetaInfo":
        import bencodepy

        data = bencodepy.decode(Path(filename).read_bytes())  # type: ignore[arg-type]
        if not isinstance(data, dict):
            raise ValueError(f"Failed to parse torrent file: {filename}")
        return cls(data)

    # region - property
    @property
    def has_info(self) -> bool:
        return self._is_refreshable()

    @property
    def info(self) -> dict[bytes, Any]:
        return self.data[b"info"]

    @property
    def info_hash(self) -> str:
        return _decode_text(self.data[b"info_hash"])

    @property
    def info_bytes(self) -> Optional[bytes]:
        if not self._is_refreshable():
            return None

        return bencodepy.encode(self.info)  # type: ignore[arg-type]

    @property
    def name(self) -> Optional[str]:
        return _decode_text(self.info.get(b"name"))

    @property
    def piece_length(self) -> Optional[int]:
        return self.info.get(b"piece length")

    @property
    def total_size(self) -> int:
        files = self.info.get(b"files")
        if isinstance(files, list): # multiple files
            total_size = 0
            for file_info in files:
                if not isinstance(file_info, dict):
                    raise ValueError("Torrent file entry is malformed")
                total_size += file_info.get(b"length", 0)
                
            return total_size
        elif b"length" in self.info: # single file
            return self.info.get(b"length", 0)
        return self.data.get(b"total_size", 0)
    # endregion

    def _is_refreshable(self) -> bool:
        mandatory_key_exist = all(key in self.info for key in (b"name", b"piece length", b"pieces"))
        file_info_exist = b"length" in self.info or b"files" in self.info
        return (mandatory_key_exist and file_info_exist)

    def refresh(self) -> None:
        if not self._is_refreshable():
            return

        info_bytes = self.info_bytes
        if info_bytes is None:
            return
        self.data[b"info_hash"] = hashlib.sha1(info_bytes).hexdigest()

    def _exportable_data(self) -> dict[bytes, Any]:
        return {
            key: value
            for key, value in self.data.items()
            if key not in (b"info_hash", b"total_size")
        }

    def update_from_info_bytes(self, metadata: bytes) -> None:
        """
        Update metainfo from bencoded ``info`` dictionary bytes.

        Args:
            metadata: Bencoded 'info' dictionary bytes

        Raises:
            ValueError: If the decoded info dictionary is malformed or the hash mismatches.
        """

        computed_hash = hashlib.sha1(metadata).hexdigest()
        if self.info_hash and computed_hash != self.info_hash:
            raise ValueError(f"Metadata hash mismatch: expected {self.info_hash}, got {computed_hash}")

        info: dict[bytes, Any] = bencodepy.decode(metadata)  # type: ignore
        if not isinstance(info, dict):
            raise ValueError("Torrent metadata info dictionary is malformed")

        self.data[b"info"] = info
        self.refresh()

    def to_bytes(self) -> bytes:

        exportable_data = self._exportable_data()
        if not self._is_refreshable():
            raise ValueError("Cannot export metainfo without an info dictionary")
        return bencodepy.encode(exportable_data)  # type: ignore[arg-type]

    def to_file(self, path: str) -> None:
        Path(path).write_bytes(self.to_bytes())
