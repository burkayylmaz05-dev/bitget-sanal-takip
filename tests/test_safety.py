import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import github_runner as runner
import github_notify as notify
import bitget_sinyal_takip as bot

class TestSafety(TestCase):
    def test_requires_telegram_secrets(self):
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            self.assertEqual(runner.main(), 2)

    def test_queue_and_no_private_settings(self):
        with TemporaryDirectory() as td, mock.patch.object(runner, "PENDING", Path(td) / "q.json"):
            runner.enqueue(["BTC SANAL", "ETH SANAL"])
            self.assertEqual(len(runner.load_pending()), 2)
            self.assertEqual(len(set(x["id"] for x in runner.load_pending())), 2)

    def test_telegram_delivered_message_removed(self):
        with TemporaryDirectory() as td:
            q = Path(td) / "queue.json"
            bot.save_json(q, [{"id": "t", "text": "TEST"}])
            with mock.patch.object(runner, "PENDING", q), mock.patch.object(notify, "PENDING", q), mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "FAKE", "TELEGRAM_CHAT_ID": "FAKE"}), mock.patch.object(notify, "telegram_post") as send:
                self.assertEqual(notify.main(), 0)
                self.assertEqual(bot.load_json(q, []), [])
                send.assert_called_once_with("FAKE", "FAKE", "TEST")

    def test_failed_delivery_retains_queue(self):
        with TemporaryDirectory() as td:
            q = Path(td) / "queue.json"
            bot.save_json(q, [{"id": "t", "text": "TEST"}])
            with mock.patch.object(runner, "PENDING", q), mock.patch.object(notify, "PENDING", q), mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "FAKE", "TELEGRAM_CHAT_ID": "FAKE"}), mock.patch.object(notify, "telegram_post", side_effect=RuntimeError("offline")):
                self.assertEqual(notify.main(), 1)
                self.assertEqual(len(bot.load_json(q, [])), 1)

    def test_no_exchange_order_calls(self):
        src = (Path(__file__).resolve().parents[1] / "bitget_sinyal_takip.py").read_text(encoding="utf-8")
        for bad in ("/api/v2/mix/order", "/api/v3/trade/place-order", "privateKey"):
            self.assertNotIn(bad, src)
