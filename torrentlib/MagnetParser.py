"""Parsing support for BitTorrent magnet URIs."""

import base64
import binascii
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class Magnet:
    """The torrent-related fields extracted from a magnet URI."""

    info_hash: str
    display_name: str | None = None
    exact_length: int | None = None
    trackers: tuple[str, ...] = ()
    peer_endpoints: tuple[tuple[str, int], ...] = ()
    parameters: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


class MagnetParser:
    """Parse and validate BitTorrent magnet URIs."""

    @classmethod
    def parse(cls, magnet_uri: str) -> Magnet:
        if not isinstance(magnet_uri, str):
            raise TypeError("magnet_uri must be a string")

        parsed = urlparse(magnet_uri)
        if parsed.scheme.lower() != "magnet":
            raise ValueError("Expected a magnet URI")

        raw_parameters = parse_qs(parsed.query, keep_blank_values=True)
        parameters = {
            key: tuple(values) for key, values in raw_parameters.items()
        }

        info_hash = cls._find_info_hash(parameters.get("xt", ()))
        if info_hash is None:
            raise ValueError("Magnet URI must contain a valid urn:btih exact topic")

        exact_length = cls._parse_exact_length(parameters.get("xl", ()))
        display_names = parameters.get("dn", ())
        trackers = tuple(tracker for tracker in parameters.get("tr", ()) if tracker)
        peer_endpoints = cls._parse_peer_endpoints(parameters.get("x.pe", ()))

        return Magnet(
            info_hash=info_hash,
            display_name=display_names[0] if display_names else None,
            exact_length=exact_length,
            trackers=trackers,
            peer_endpoints=peer_endpoints,
            parameters=MappingProxyType(parameters),
        )

    @staticmethod
    def _find_info_hash(exact_topics: tuple[str, ...]) -> str | None:
        """
        Parse `xt` to infohash HEX
        """
        for exact_topic in exact_topics:
            prefix, separator, encoded_hash = exact_topic.rpartition(":")
            # consume "urn:btih:"
            if not separator or prefix.lower() != "urn:btih":
                continue
            
            # decode infohash to byte
            try:
                if len(encoded_hash) == 40:
                    decoded = bytes.fromhex(encoded_hash)
                elif len(encoded_hash) == 32:
                    decoded = base64.b32decode(encoded_hash.upper(), casefold=True)
                else:
                    continue
            except (ValueError, binascii.Error):
                continue
            
            # encode byte to hex
            if len(decoded) == 20:
                return decoded.hex()
        return None

    @staticmethod
    def _parse_exact_length(values: tuple[str, ...]) -> int | None:
        """
        Parse and validate `xl`
        """
        
        if not values:
            return None
        try:
            exact_length = int(values[0])
        except ValueError as exc:
            raise ValueError("Magnet URI xl must be a non-negative integer") from exc
        if exact_length < 0:
            raise ValueError("Magnet URI xl must be a non-negative integer")
        return exact_length

    @staticmethod
    def _parse_peer_endpoints(values: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
        endpoints: list[tuple[str, int]] = []
        for value in values:
            host = ""
            port_text = ""
            if value.startswith("["):
                closing_bracket = value.find("]")
                if closing_bracket != -1 and value[closing_bracket + 1:].startswith(":"):
                    host = value[1:closing_bracket]
                    port_text = value[closing_bracket + 2:]
            else:
                host, separator, port_text = value.rpartition(":")
                if not separator:
                    host = ""

            try:
                port = int(port_text)
            except ValueError:
                continue
            endpoint = (host, port)
            if host and 1 <= port <= 65535 and endpoint not in endpoints:
                endpoints.append(endpoint)
        return tuple(endpoints)
