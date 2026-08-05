"""Tests for `whatbot/storage/` (conversation-history-media-storage).

`LocalDiskStorage` is the only backend implemented today — see
`whatbot/storage/factory.py` for why `s3` raises `NotImplementedError`.
"""

import tempfile
import unittest
from pathlib import Path

from whatbot.storage import (
    BACKEND_LOCAL,
    BACKEND_S3,
    LocalDiskStorage,
    StorageError,
    build_storage_backend,
)


class TestLocalDiskStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = LocalDiskStorage(self._tmp.name)

    def test_save_then_open_roundtrip(self):
        self.storage.save("whatsapp/2026/08/1/abc.ogg", b"conteudo binario")
        self.assertEqual(
            self.storage.open("whatsapp/2026/08/1/abc.ogg"), b"conteudo binario"
        )

    def test_save_creates_parent_directories(self):
        self.storage.save("a/b/c/d.bin", b"x")
        self.assertTrue((Path(self._tmp.name) / "a" / "b" / "c" / "d.bin").exists())

    def test_open_missing_key_raises_storage_error(self):
        with self.assertRaises(StorageError):
            self.storage.open("nao/existe.bin")

    def test_path_traversal_via_dotdot_is_rejected(self):
        with self.assertRaises(StorageError):
            self.storage.save("../escaped.bin", b"x")
        with self.assertRaises(StorageError):
            self.storage.open("../../etc/passwd")

    def test_absolute_key_is_rejected(self):
        with self.assertRaises(StorageError):
            self.storage.save("/etc/passwd", b"x")

    def test_empty_key_is_rejected(self):
        with self.assertRaises(StorageError):
            self.storage.save("", b"x")

    def test_url_returns_none_no_static_file_server(self):
        self.storage.save("a.bin", b"x")
        self.assertIsNone(self.storage.url("a.bin"))


class TestBuildStorageBackend(unittest.TestCase):
    def test_local_backend_is_built(self):
        backend = build_storage_backend(BACKEND_LOCAL, "/tmp/whatever")
        self.assertIsInstance(backend, LocalDiskStorage)

    def test_default_backend_when_empty_is_local(self):
        backend = build_storage_backend("", "/tmp/whatever")
        self.assertIsInstance(backend, LocalDiskStorage)

    def test_s3_backend_is_not_implemented_yet(self):
        with self.assertRaises(NotImplementedError):
            build_storage_backend(BACKEND_S3, "/tmp/whatever")

    def test_unknown_backend_raises_value_error(self):
        with self.assertRaises(ValueError):
            build_storage_backend("dropbox", "/tmp/whatever")


if __name__ == "__main__":
    unittest.main()
