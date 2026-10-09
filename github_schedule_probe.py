# -*- coding: utf-8 -*-
"""Single, auditable Telegram message on FIRST actual GitHub schedule run.
Does not send an order and never handles secrets itself.
"""
import datetime as dt
import hashlib
import os
from pathlib import Path

import bitget_sinyal_takip as bot
from github_runner import PENDING, MAX_PENDING, load_pending

ROOT = Path(__file__).resolve().parent
PROOF = ROOT / "github_schedule_verified.json"


def confirm_schedule():
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        print("Zamanlama kaniti: schedule tetiklemesi degil, islem yok.")
        return
    if PROOF.exists():
        print("Zamanlama kaniti daha once kaydedildi.")
        return
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        print("Zamanlama kaniti beklemede: Telegram Secrets eksik.")
        return
    queue = load_pending()
    if len(queue) >= MAX_PENDING:
        raise RuntimeError("Bildirim kuyrugu dolu; kanit yazilmadi")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    message = ("✅ Bitget botunun 5 dakikalik OTOMATIK GitHub zamanlamasi ilk kez "
               "gercekten calisti. UTC zaman: " + now +
               ". Sanal strateji takibi etkin. Gercek emir YOK. "
               "GitHub zamanlama gecikmeleri yine de olabilir.")
    uid = hashlib.sha256(("schedule-proof:" + now).encode("utf-8")).hexdigest()[:20]
    queue.append({"id": uid, "text": message})
    bot.save_json(PENDING, queue)
    bot.save_json(PROOF, {"first_confirmed_schedule_utc": now})
    print("Zamanlama kaniti olusturuldu; bildirim kuyruğa eklendi.")


if __name__ == "__main__":
    confirm_schedule()
