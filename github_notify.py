# -*- coding: utf-8 -*-
"""Deliver queued Telegram messages after paper-state commit."""
import json
import os
import urllib.parse
import urllib.request
from github_runner import load_pending, PENDING
import bitget_sinyal_takip as b

def telegram_post(token, chat, message):
    body = urllib.parse.urlencode({"chat_id": chat, "text": message}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=body, headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.load(response)
    if not data.get("ok"):
        raise RuntimeError("Telegram API mesaj gonderimini reddetti")

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("Telegram Secrets eklenmedi; sanal test devam eder, bildirim kapali.")
        return 0
    todo = load_pending()
    count = 0
    while todo and count < 20:
        try:
            telegram_post(token, chat, todo[0]["text"])
        except Exception as exc:
            print("Telegram iletim hatasi:", type(exc).__name__)
            b.save_json(PENDING, todo)
            return 1
        todo.pop(0)
        count += 1
        b.save_json(PENDING, todo)
    print("Telegram mesajlari:", count, "kalan:", len(todo))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
