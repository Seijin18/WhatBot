"""Tests for `whatbot.config.force_ipv4_dns` (`whatsapp-send-resilience`).

`socket.getaddrinfo` is restored after every test via `addCleanup`, since
`force_ipv4_dns` patches it at module scope — leaking the patch across test
files would be a real bug (every DNS lookup in the whole suite would go
through the wrapper).
"""

import socket
import unittest

from whatbot import config


def _fake_getaddrinfo(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0)),
    ]


def _fake_getaddrinfo_ipv6_only(host, port, *args, **kwargs):
    return [
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0)),
    ]


class TestForceIpv4Dns(unittest.TestCase):
    def setUp(self):
        self._original_getaddrinfo = socket.getaddrinfo
        # Reset the module's "already patched" flag so each test observes a
        # fresh `force_ipv4_dns()` call, regardless of what earlier test
        # modules (or an earlier test in this file) already did.
        config._ipv4_dns_forced = False
        self.addCleanup(self._restore)

    def _restore(self):
        socket.getaddrinfo = self._original_getaddrinfo
        config._ipv4_dns_forced = False

    def test_filters_out_ipv6_results(self):
        socket.getaddrinfo = _fake_getaddrinfo
        config.force_ipv4_dns()

        results = socket.getaddrinfo("example.com", 443)

        self.assertTrue(all(r[0] == socket.AF_INET for r in results))
        self.assertEqual(len(results), 1)

    def test_ipv6_only_host_still_returns_something(self):
        # Degrade, don't break: an IPv6-only host must not end up with an
        # empty result list just because we prefer IPv4.
        socket.getaddrinfo = _fake_getaddrinfo_ipv6_only
        config.force_ipv4_dns()

        results = socket.getaddrinfo("ipv6-only.example.com", 443)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], socket.AF_INET6)

    def test_is_idempotent(self):
        socket.getaddrinfo = _fake_getaddrinfo
        config.force_ipv4_dns()
        patched_once = socket.getaddrinfo

        config.force_ipv4_dns()

        self.assertIs(socket.getaddrinfo, patched_once)


if __name__ == "__main__":
    unittest.main()
