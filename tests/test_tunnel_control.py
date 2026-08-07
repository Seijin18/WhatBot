"""Tests for `whatbot/tunnel_control.py` — ferramenta operacional temporária
(sem network real: `subprocess.Popen` e `requests.get` são mockados)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from whatbot import tunnel_control


class TunnelControlTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.url_file = Path(self._tmp.name) / ".tunnel-url"
        self.log_file = Path(self._tmp.name) / "tunnel-ui.log"

        patches = [
            patch.object(tunnel_control, "URL_FILE", self.url_file),
            patch.object(tunnel_control, "_LOG_FILE", self.log_file),
            patch.object(tunnel_control, "_process", None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # Reset the module lock's owner state isn't needed (a fresh
        # threading.Lock isn't held across tests), but be explicit that no
        # leftover process reference survives between tests.
        self.addCleanup(setattr, tunnel_control, "_process", None)


class TestGetStatus(TunnelControlTestCase):
    def test_no_url_file_is_not_reachable(self):
        status = tunnel_control.get_status()
        self.assertIsNone(status["url"])
        self.assertFalse(status["reachable"])

    def test_url_file_present_and_reachable(self):
        self.url_file.write_text("https://example.trycloudflare.com\n")
        response = MagicMock(ok=True)
        with patch("whatbot.tunnel_control.requests.get", return_value=response):
            status = tunnel_control.get_status()
        self.assertEqual(status["url"], "https://example.trycloudflare.com")
        self.assertTrue(status["reachable"])

    def test_url_file_present_but_unreachable(self):
        self.url_file.write_text("https://dead.trycloudflare.com\n")
        with patch(
            "whatbot.tunnel_control.requests.get",
            side_effect=tunnel_control.requests.RequestException("sem rede"),
        ):
            status = tunnel_control.get_status()
        self.assertEqual(status["url"], "https://dead.trycloudflare.com")
        self.assertFalse(status["reachable"])


class TestStartTunnel(TunnelControlTestCase):
    def test_already_reachable_does_not_spawn_a_new_process(self):
        self.url_file.write_text("https://already-up.trycloudflare.com\n")
        response = MagicMock(ok=True)
        with patch("whatbot.tunnel_control.requests.get", return_value=response), patch(
            "whatbot.tunnel_control.subprocess.Popen"
        ) as popen_mock:
            result = tunnel_control.start_tunnel(8090)

        popen_mock.assert_not_called()
        self.assertFalse(result["started"])
        self.assertTrue(result["reachable"])

    def test_spawns_process_and_parses_url_from_log(self):
        def fake_popen(*args, **kwargs):
            # Simula o cloudflared escrevendo a URL no log assim que "sobe".
            self.log_file.write_text(
                "Your quick Tunnel has been created!\n"
                "https://fresh-tunnel.trycloudflare.com\n"
            )
            proc = MagicMock()
            proc.poll.return_value = None
            return proc

        unreachable = tunnel_control.requests.RequestException("ainda não")
        reachable_response = MagicMock(ok=True)

        with patch(
            "whatbot.tunnel_control.requests.get",
            side_effect=[unreachable, reachable_response],
        ), patch("whatbot.tunnel_control.subprocess.Popen", side_effect=fake_popen):
            result = tunnel_control.start_tunnel(8090)

        self.assertTrue(result["started"])
        self.assertEqual(result["url"], "https://fresh-tunnel.trycloudflare.com")
        self.assertEqual(self.url_file.read_text().strip(), "https://fresh-tunnel.trycloudflare.com")

    def test_cloudflared_missing_returns_clear_detail(self):
        with patch("whatbot.tunnel_control.requests.get", side_effect=tunnel_control.requests.RequestException()), \
             patch("whatbot.tunnel_control.subprocess.Popen", side_effect=FileNotFoundError):
            result = tunnel_control.start_tunnel(8090)

        self.assertFalse(result["started"])
        self.assertIn("cloudflared", result["detail"])

    def test_process_still_running_is_not_duplicated(self):
        running_process = MagicMock()
        running_process.poll.return_value = None
        with patch.object(tunnel_control, "_process", running_process), patch(
            "whatbot.tunnel_control.requests.get",
            side_effect=tunnel_control.requests.RequestException(),
        ), patch("whatbot.tunnel_control.subprocess.Popen") as popen_mock:
            result = tunnel_control.start_tunnel(8090)

        popen_mock.assert_not_called()
        self.assertFalse(result["started"])


if __name__ == "__main__":
    unittest.main()
