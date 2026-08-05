"""Storage abstraction: the contract every media storage backend must satisfy.

Mirrors `whatbot/channels/base.py` in spirit (a `Protocol` + free functions,
no dependency-injection framework) — see
`openspec/changes/conversation-history-media-storage/design.md`, Decisão 3.

Every backend is addressed by a *relative* `key` (e.g.
`whatsapp/2026/08/42/9f3e....ogg`), never an absolute filesystem path or a
full URL — that is the contract that lets `media_arquivos.storage_key` mean
the same thing whether `storage_backend` is `local` or (later) `s3`:
switching backends is reprocessing the same keys, not redesigning the schema.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Raised when a storage backend cannot save, read, or resolve a key."""


@runtime_checkable
class StorageBackend(Protocol):
    """Contract implemented by every media storage backend."""

    def save(self, key: str, data: bytes, content_type: str | None = None) -> None:
        """Persist `data` under `key`, creating any parent structure needed."""
        ...

    def open(self, key: str) -> bytes:
        """Return the bytes stored under `key`.

        Raises `StorageError` if `key` does not exist.
        """
        ...

    def url(self, key: str) -> str | None:
        """A directly fetchable URL for `key`, or `None` if the backend has
        none (e.g. local disk, served instead through an authenticated
        application route rather than a static file server)."""
        ...
