"""Local-disk `StorageBackend` — the only backend implemented today.

Rudimentary on purpose (see `openspec/changes/conversation-history-media-storage/proposal.md`):
runs against a plain directory on the machine hosting the bot, no external
service required. `MEDIA_STORAGE_ROOT`/`MEDIA_STORAGE_BACKEND` (see
`whatbot/config.py`) select and configure it; swapping to a cloud backend
later (e.g. S3) means writing a new class satisfying `StorageBackend` and
changing `MEDIA_STORAGE_BACKEND` — the `storage_key`s already stored in
`media_arquivos` are reused unchanged as object keys.
"""

from __future__ import annotations

from pathlib import Path

from .base import StorageError


class LocalDiskStorage:
    """Stores files under `root_dir`, keyed by a relative `key`."""

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir).resolve()

    def _resolve(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise StorageError(f"chave de storage inválida: {key!r}")
        path = (self.root_dir / key).resolve()
        try:
            path.relative_to(self.root_dir)
        except ValueError:
            # `key` resolved to outside `root_dir` (path traversal, e.g. via
            # a symlink-adjacent trick the `..` check above didn't catch) —
            # refuse rather than write/read outside the configured root.
            raise StorageError(f"chave de storage fora do root: {key!r}")
        return path

    def save(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_bytes(data)
        except OSError as e:
            raise StorageError(f"falha gravando {key!r}: {e}") from e

    def open(self, key: str) -> bytes:
        path = self._resolve(key)
        try:
            return path.read_bytes()
        except OSError as e:
            raise StorageError(f"falha lendo {key!r}: {e}") from e

    def url(self, key: str) -> str | None:
        # No static file server in front of `root_dir` — callers fetch the
        # bytes through an authenticated application route
        # (`GET /admin/midia/{id}` em `whatbot/ingress.py`), not a direct URL.
        return None
