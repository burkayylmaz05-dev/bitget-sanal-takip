# -*- coding: utf-8 -*-
"""One-time Telegram delivery verification, run on code push/manual trigger only."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("TELEGRAM TEST FAILED: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub secret.")
        return 2
    if any(ch.isspace() for ch in token) or any(ch.isspace() for ch in chat_id):
        print("TELEGRAM TEST FAILED: secret contains whitespace.")
        return 2
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": "✅ Bitget sanal takip GitHub testi basarili. Telegram baglantisi aktif. BTC A/B sanal izleme suruyor. GERCEK EMIR YOK."
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print("TELEGRAM TEST FAILED: Telegram API HTTP status", exc.code,
              "(check bot token, chat ID, and bot Start); no credentials logged.")
        return 1
    except Exception:
        print("TELEGRAM TEST FAILED: network or transport issue, no credentials logged.")
        return 1
    if not result.get("ok"):
        print("TELEGRAM TEST FAILED: Telegram rejected message, no credentials logged.")
        return 1
    print("TELEGRAM TEST SUCCESS: Test message accepted by Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
