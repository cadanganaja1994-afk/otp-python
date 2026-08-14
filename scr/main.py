import os
import json
import hmac
import hashlib
import requests
from datetime import datetime

# Config (Ambil dari Cloudflare Environment Variables)
API_KEY = os.getenv("OTP_API_KEY")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WH_SECRET = os.getenv("WH_SECRET") # 'wh_xxxxx'
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HEADERS = {"X-Api-Key": API_KEY}

def verify_signature(body, signature):
    """Memverifikasi HMAC SHA256 dari Cloudflare/Webhook"""
    if not signature:
        return False
    expected = hmac.new(
        WH_SECRET.encode(),
        body.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)

async def store_history(kv, user_id, order_data):
    """Menyimpan riwayat order ke Cloudflare KV"""
    key = f"history_{user_id}"
    existing = await kv.get(key)
    history = json.loads(existing) if existing else []
    
    # Tambahkan order baru di posisi atas
    order_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M")
    history.insert(0, order_data)
    
    # Simpan max 10 riwayat terakhir agar KV tidak bengkak
    await kv.put(key, json.dumps(history[:10]))

async def on_request(request, env):
    # Cloudflare KV Namespace
    KV = env.OTP_DATA 
    
    if request.method != "POST":
        return Response("Method Not Allowed", status=405)

    body = await request.text()
    signature = request.headers.get("x-signature")

    # 1. VERIFY SIGNATURE (Security)
    if not verify_signature(body, signature):
        return Response("Unauthorized", status=401)

    data = json.loads(body)

    # --- LOGIKA WEBHOOK OTP RECEIVED (DARI SERVER) ---
    if data.get("event") == "otp.received":
        order_id = data.get("order_id")
        otp_code = data.get("otp_code")
        # Cari user_id berdasarkan order_id di KV jika perlu, 
        # atau kirim ke chat_id yang tersimpan.
        # (Asumsi: Anda mengirim chat_id di metadata atau menyimpannya di KV)
        return Response("OTP Processed", status=200)

    # --- LOGIKA TELEGRAM WEBHOOK ---
    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text == "/start":
            return await send_main_menu(chat_id)
        
        elif text.startswith("/cek"):
            order_id = text.split(" ")[1]
            return await check_status(chat_id, order_id)

    elif "callback_query" in data:
        query = data["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        msg_id = query["message"]["message_id"]
        cb_data = query["data"].split("|")
        cmd = cb_data[0]

        if cmd == "menu_balance":
            return await get_balance(chat_id, msg_id)
        
        elif cmd == "menu_history":
            return await get_history(chat_id, msg_id, KV)
        
        elif cmd == "srv":
            # Logika Beli (Sama seperti sebelumnya, panggil API S1/S2/S5)
            # Setelah order sukses, panggil:
            # await store_history(KV, chat_id, {"order_id": "...", "phone": "..."})
            pass

    return Response("OK", status=200)

# --- HELPER FUNCTIONS ---

async def send_main_menu(chat_id):
    markup = {
        "inline_keyboard": [
            [{"text": "🛒 Beli Nomor", "callback_data": "menu_buy"}],
            [{"text": "💰 Saldo", "callback_data": "menu_balance"}, {"text": "📜 Riwayat", "callback_data": "menu_history"}],
            [{"text": "💳 Top Up", "callback_data": "menu_topup"}]
        ]
    }
    requests.post(f"{TELEGRAM_API}/sendMessage", json={
        "chat_id": chat_id,
        "text": "🔥 *OTP INSTAN BOT*\nSecure & Fast OTP Provider",
        "parse_mode": "Markdown",
        "reply_markup": markup
    })

async def get_balance(chat_id, msg_id):
    res = requests.get("https://otpinstan.com/api/reseller/balance.php", headers=HEADERS).json()
    balance = res.get("balance_formatted", "Rp 0")
    markup = {"inline_keyboard": [[{"text": "⬅️ Kembali", "callback_data": "main"}]]}
    requests.post(f"{TELEGRAM_API}/editMessageText", json={
        "chat_id": chat_id, "message_id": msg_id,
        "text": f"💳 *Saldo Anda:* `{balance}`",
        "parse_mode": "Markdown", "reply_markup": markup
    })

async def get_history(chat_id, msg_id, kv):
    key = f"history_{chat_id}"
    data = await kv.get(key)
    if not data:
        txt = "📭 Belum ada riwayat transaksi."
    else:
        history = json.loads(data)
        txt = "📜 *10 Transaksi Terakhir:*\n\n"
        for item in history:
            txt += f"• `{item['order_id']}` | {item['phone']} | {item['timestamp']}\n"
    
    markup = {"inline_keyboard": [[{"text": "⬅️ Kembali", "callback_data": "main"}]]}
    requests.post(f"{TELEGRAM_API}/editMessageText", json={
        "chat_id": chat_id, "message_id": msg_id,
        "text": txt, "parse_mode": "Markdown", "reply_markup": markup
    })
