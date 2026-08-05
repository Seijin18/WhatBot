"""Selects the configured `StorageBackend` from environment variables.

See `whatbot/config.py` (`ENV_MEDIA_STORAGE_BACKEND`, `ENV_MEDIA_STORAGE_ROOT`)
for the env vars and defaults, and
`openspec/changes/conversation-history-media-storage/design.md` Decisão 3
for why backends are addressed by a relative key rather than a path/URL.
"""

from __future__ import annotations

from .base import StorageBackend
from .local import LocalDiskStorage

BACKEND_LOCAL = "local"
BACKEND_S3 = "s3"
SUPPORTED_BACKENDS = (BACKEND_LOCAL, BACKEND_S3)

_cached_backend: StorageBackend | None = None
_cached_backend_key: tuple[str, str] | None = None


def build_storage_backend(backend: str, root_dir: str) -> StorageBackend:
    """Construct a fresh `StorageBackend` for `backend` — no caching.

    Split out from `get_storage_backend()` so tests can build an isolated
    instance (e.g. a temp dir) without touching the process-wide cache.
    """
    normalized = (backend or BACKEND_LOCAL).strip().lower()
    if normalized == BACKEND_LOCAL:
        return LocalDiskStorage(root_dir)
    if normalized == BACKEND_S3:
        # Reserved, not implemented in this change — see proposal.md,
        # "Fora de escopo": só vale a pena escrever quando a operação for
        # migrar de fato para um serviço em nuvem.
        raise NotImplementedError(
            "MEDIA_STORAGE_BACKEND='s3' ainda não está implementado — "
            "só 'local' está disponível nesta etapa."
        )
    raise ValueError(
        f"MEDIA_STORAGE_BACKEND desconhecido: {backend!r} "
        f"(esperado um de {SUPPORTED_BACKENDS})"
    )


def get_storage_backend() -> StorageBackend:
    """Process-wide cached backend, built from `MEDIA_STORAGE_BACKEND`/
    `MEDIA_STORAGE_ROOT` (env vars, see `whatbot/config.py`)."""
    global _cached_backend, _cached_backend_key

    from ..config import get_media_storage_backend, get_media_storage_root

    backend_name = get_media_storage_backend()
    root_dir = get_media_storage_root()
    cache_key = (backend_name, root_dir)
    if _cached_backend is None or _cached_backend_key != cache_key:
        _cached_backend = build_storage_backend(backend_name, root_dir)
        _cached_backend_key = cache_key
    return _cached_backend
