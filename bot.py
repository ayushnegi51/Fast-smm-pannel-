import sqlite3
import threading
import time
import requests
import telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- CONFIGURATION ---
BOT_TOKEN = "8972619522:AAHu_I3ccCdsUX-VFGjK8ihMbRAkICdUBN8"
SMMRAJA_API_URL = "https://smmraja.com/api/v2"
SMMRAJA_API_KEY = "7*B5@jWQ@0LHJ8AEH*x@"
UPI_ID = "aayushnegi486@okaxis"
QR_CODE_IMAGE_URL = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi%3A%2F%2Fpay%3Fpa%3Daayushnegi486%40okaxis%26pn%3DFast%20SMM%20Panel"
ADMIN_ID = 6478868514
OWNER_HANDLE = "@aayushnegi51"

# 💰 PRICING & CONVERSION CONFIG
USD_TO_INR_RATE = 85.0  # 1 USD = ₹85
FIXED_PROFIT_PER_1K = 2.0  # 🎯 Har 1000 quantity par fix ₹2 ka profit margin!
LOW_BALANCE_THRESHOLD = 2.0

bot = telebot.TeleBot(BOT_TOKEN)
user_data = {}

# --- CACHE FOR FAST PERFORMANCE ---
SERVICES_CACHE = []
CACHE_TIME = 0

def get_cached_services():
    global SERVICES_CACHE, CACHE_TIME
    current_time = time.time()
    if not SERVICES_CACHE or (current_time - CACHE_TIME > 600):
        try:
            res = requests.post(SMMRAJA_API_URL, data={"key": SMMRAJA_API_KEY, "action": "services"}, timeout=15).json()
            if isinstance(res, list):
                SERVICES_CACHE = res
                CACHE_TIME = current_time
        except Exception as e:
            print("API Cache Error:", e)
    return SERVICES_CACHE

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0.0, spent REAL DEFAULT 0.0, referred_by INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS orders (order_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, smm_order_id INTEGER, service_name TEXT, link TEXT, quantity INTEGER, total_price REAL, status TEXT DEFAULT 'Pending')")
    cursor.execute("CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, amount REAL, uses_left INTEGER)")
    conn.commit()
    conn.close()

init_db()

def get_or_create_user(user_id, username, referrer_id=0):
    conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT balance, spent FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        ref_to_save = 0
        if referrer_id and referrer_id != user_id:
            cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (referrer_id,))
            if cursor.fetchone():
                ref_to_save = referrer_id
                cursor.execute("UPDATE users SET balance = balance + 5.0 WHERE user_id = ?", (referrer_id,))
                try:
                    bot.send_message(referrer_id, "🎁 <b>Referral Bonus!</b> Someone joined using your link. ₹5.00 added to your wallet!", parse_mode="HTML")
                except:
                    pass
        cursor.execute("INSERT INTO users (user_id, username, balance, spent, referred_by) VALUES (?, ?, 0.0, 0.0, ?)", (user_id, username, ref_to_save))
        conn.commit()
        balance, spent = 0.0, 0.0
    else:
        balance, spent = user
    conn.close()
    return balance, spent

def calculate_selling_rate(rate_usd):
    try:
        rate_float = float(rate_usd)
        rate_inr_per_1k = rate_float * USD_TO_INR_RATE
        selling_rate_per_1k = rate_inr_per_1k + FIXED_PROFIT_PER_1K
        return round(selling_rate_per_1k, 2)
    except:
        return 0.0

# --- BACKGROUND WORKER ---
def background_workers():
    while True:
        try:
            conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("SELECT order_id, user_id, smm_order_id, status FROM orders WHERE status NOT IN ('Completed', 'Canceled', 'Partial')")
            pending_orders = cursor.fetchall()
            for ord_db_id, u_id, smm_id, current_status in pending_orders:
                payload = {"key": SMMRAJA_API_KEY, "action": "status", "order": smm_id}
                res = requests.post(SMMRAJA_API_URL, data=payload, timeout=10).json()
                if "status" in res:
                    new_status = res["status"]
                    if new_status != current_status:
                        cursor.execute("UPDATE orders SET status = ? WHERE order_id = ?", (new_status, ord_db_id))
                        conn.commit()
                        try:
                            bot.send_message(u_id, f"🔔 <b>Order Status Updated!</b>\n\n🆔 <b>DB ID:</b> {ord_db_id}\n📌 <b>SMM ID:</b> {smm_id}\n📊 <b>New Status:</b> <b>{new_status}</b>", parse_mode="HTML")
                        except:
                            pass
                time.sleep(1)
            conn.close()

            try:
                bal_res = requests.post(SMMRAJA_API_URL, data={"key": SMMRAJA_API_KEY, "action": "balance"}).json()
                if "balance" in bal_res:
                    curr_bal = float(bal_res["balance"])
                    if curr_bal < LOW_BALANCE_THRESHOLD:
                        bot.send_message(ADMIN_ID, f"⚠️ <b>LOW BALANCE ALERT!</b>\nYour SMMRaja main balance has dropped to <b>${curr_bal}</b>. Recharge immediately!", parse_mode="HTML")
            except Exception as ex:
                print("Balance Alert Error:", ex)

        except Exception as e:
            print("Background worker error:", e)
        time.sleep(300)

threading.Thread(target=background_workers, daemon=True).start()

# --- ADMIN COMMANDS: BALANCE CHECKER & BROADCAST ---
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        res = requests.post(SMMRAJA_API_URL, data={"key": SMMRAJA_API_KEY, "action": "balance"}, timeout=10).json()
        smm_balance_usd = float(res.get("balance", 0.0))
        smm_balance_inr = smm_balance_usd * USD_TO_INR_RATE

        conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(balance), SUM(spent) FROM users")
        total_users, total_wallet_bal, total_spent = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM orders")
        total_orders = cursor.fetchone()[0]
        conn.close()

        admin_text = (
            f"👑 <b>ADMIN CONTROL PANEL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 <b>SMMRaja API Balance:</b> <code>${smm_balance_usd:.4f}</code> (≈ ₹{smm_balance_inr:.2f})\n"
            f"👥 <b>Total Bot Users:</b> {total_users or 0}\n"
            f"📦 <b>Total Orders Placed:</b> {total_orders or 0}\n"
            f"💰 <b>User Wallets Bal:</b> ₹{total_wallet_bal or 0.0:.2f}\n"
            f"💸 <b>Total Revenue Spent:</b> ₹{total_spent or 0.0:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📢 <i>Use /broadcast [message] to send notice.</i>\n"
            f"👤 <b>Owner:</b> {OWNER_HANDLE}"
        )
        bot.send_message(message.chat.id, admin_text, parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error fetching admin stats: {str(e)}", parse_mode="HTML")

@bot.message_handler(commands=['broadcast'])
def broadcast_message(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ <b>Usage format:</b> <code>/broadcast Your message here</code>", parse_mode="HTML")
        return
    
    broadcast_text = parts[1]
    
    conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    all_users = cursor.fetchall()
    conn.close()

    msg_sent = 0
    msg_failed = 0

    status_msg = bot.send_message(message.chat.id, "⏳ <b>Broadcasting message to all users... Please wait.</b>", parse_mode="HTML")

    for u in all_users:
        u_id = u[0]
        try:
            bot.send_message(u_id, f"📢 <b>ANNOUNCEMENT</b>\n━━━━━━━━━━━━━━━━━━━\n{broadcast_text}\n━━━━━━━━━━━━━━━━━━━\n\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
            msg_sent += 1
            time.sleep(0.1)
        except:
            msg_failed += 1

    bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=status_msg.message_id,
        text=f"✅ <b>Broadcast Completed!</b>\n\n📤 Sent: {msg_sent}\n❌ Failed: {msg_failed}",
        parse_mode="HTML"
    )

# --- PAYMENT PROOF HANDLER ---
def process_payment_proof(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    proof_text = message.text if message.text else (message.caption if message.caption else "Photo/Document Proof")

    MIN_DEPOSIT_AMOUNT = 30.0

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve (₹30)", callback_data=f"approve_{user_id}_30.0"),
        InlineKeyboardButton("✅ Approve (₹50)", callback_data=f"approve_{user_id}_50.0"),
        InlineKeyboardButton("✅ Approve (₹100)", callback_data=f"approve_{user_id}_100.0"),
        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
    )

    admin_caption = (
        f"💳 <b>NEW PAYMENT PROOF SUBMITTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> @{username} (<code>{user_id}</code>)\n"
        f"📝 <b>Text/UTR:</b> {proof_text}\n"
        f"⚠️ <i>Note: Minimum deposit allowed is ₹{MIN_DEPOSIT_AMOUNT}. Verify payment before approving.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )

    if message.photo:
        file_id = message.photo[-1].file_id
        bot.send_photo(ADMIN_ID, file_id, caption=admin_caption, parse_mode="HTML", reply_markup=markup)
    else:
        bot.send_message(ADMIN_ID, admin_caption, parse_mode="HTML", reply_markup=markup)

    bot.send_message(message.chat.id, f"✅ <b>Payment proof submitted successfully!</b>\nAdmin will verify your payment (Minimum deposit: ₹{MIN_DEPOSIT_AMOUNT}), and funds will be added to your wallet shortly.", parse_mode="HTML")

def process_coupon_redemption(message):
    pass

def get_link_dynamic(message):
    user_id = message.from_user.id
    link = message.text.strip()
    service_data = user_data.get(user_id, {}).get("selected_service")
    if not service_data:
        bot.send_message(message.chat.id, "❌ Session expired. Please start again from /start", parse_mode="HTML")
        return

    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]["target_link"] = link

    min_q = int(service_data.get("min", 10))
    max_q = int(service_data.get("max", 500000))
    
    msg = bot.send_message(message.chat.id, f"🔢 <b>Enter Quantity</b> (Min: {min_q}, Max: {max_q}):", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_quantity_dynamic)

def process_quantity_dynamic(message):
    user_id = message.from_user.id
    try:
        qty = int(message.text.strip())
    except:
        bot.send_message(message.chat.id, "❌ Invalid quantity. Enter a valid number:", parse_mode="HTML")
        return

    service_data = user_data.get(user_id, {}).get("selected_service")
    link = user_data.get(user_id, {}).get("target_link")
    if not service_data or not link:
        bot.send_message(message.chat.id, "❌ Session expired. Type /start", parse_mode="HTML")
        return

    min_q = int(service_data.get("min", 10))
    max_q = int(service_data.get("max", 500000))

    if qty < min_q or qty > max_q:
        bot.send_message(message.chat.id, f"❌ Quantity must be between {min_q} and {max_q}. Try again:", parse_mode="HTML")
        return

    selling_rate_per_1k = service_data.get("selling_rate", 0.0)
    total_price = (selling_rate_per_1k * qty) / 1000.0
    total_price = round(total_price, 2)

    balance, _ = get_or_create_user(user_id, message.from_user.username or message.from_user.first_name)

    if balance < total_price:
        bot.send_message(message.chat.id, f"❌ <b>Insufficient Balance!</b>\nRequired: ₹{total_price:.2f}\nYour Balance: ₹{balance:.2f}\nPlease add funds to your wallet.", parse_mode="HTML")
        return

    payload = {
        "key": SMMRAJA_API_KEY,
        "action": "add",
        "service": service_data.get("service"),
        "link": link,
        "quantity": qty
    }
    try:
        res = requests.post(SMMRAJA_API_URL, data=payload, timeout=15).json()
        if "order" in res:
            smm_order_id = res["order"]
            
            conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance - ?, spent = spent + ? WHERE user_id = ?", (total_price, total_price, user_id))
            cursor.execute("INSERT INTO orders (user_id, smm_order_id, service_name, link, quantity, total_price, status) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                           (user_id, smm_order_id, service_data.get("name"), link, qty, total_price, "Pending"))
            conn.commit()
            conn.close()

            success_text = (
                f"✅ <b>ORDER PLACED SUCCESSFULLY!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Service:</b> {service_data.get('name')}\n"
                f"🔗 <b>Link:</b> {link}\n"
                f"🔢 <b>Quantity:</b> {qty}\n"
                f"💸 <b>Total Cost:</b> ₹{total_price:.2f}\n"
                f"🆔 <b>SMM Order ID:</b> {smm_order_id}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Owner:</b> {OWNER_HANDLE}"
            )
            bot.send_message(message.chat.id, success_text, parse_mode="HTML")
        else:
            err_msg = res.get("error", "Unknown API Error")
            bot.send_message(message.chat.id, f"❌ <b>Order Failed by API:</b>\n<code>{err_msg}</code>", parse_mode="HTML")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Connection Error: {str(e)}", parse_mode="HTML")

# --- START & MENUS ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    args = message.text.split()
    referrer_id = int(args[1].replace("ref_", "")) if len(args) > 1 and args[1].startswith("ref_") else 0
    balance, _ = get_or_create_user(user_id, username, referrer_id)

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🛒 New Order", callback_data="new_order"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds"),
        InlineKeyboardButton("👤 My Account", callback_data="account"),
        InlineKeyboardButton("📦 My Orders", callback_data="my_orders"),
        InlineKeyboardButton("🎁 Refer & Earn", callback_data="referral"),
        InlineKeyboardButton("🎟️ Redeem Coupon", callback_data="redeem_menu")
    )
    welcome_text = (
        f"🌟 <b>WELCOME TO FAST SMM PANEL</b> 🌟\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Account Name:</b> {message.from_user.first_name}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"💰 <b>Wallet Balance:</b> ₹{balance:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<i>💡 Select an option from below to continue:</i>\n\n"
        f"👤 <b>Owner:</b> {OWNER_HANDLE}"
    )
    bot.send_message(message.chat.id, welcome_text, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    username = call.from_user.username or call.from_user.first_name

    if call.data == "account":
        bot.answer_callback_query(call.id)
        balance, spent = get_or_create_user(user_id, username)
        bot.send_message(call.message.chat.id, f"👤 <b>ACCOUNT INFORMATION</b>\n━━━━━━━━━━━━━━━━━━━\n🆔 <b>User ID:</b> <code>{user_id}</code>\n💰 <b>Current Balance:</b> ₹{balance:.2f}\n💸 <b>Total Spent:</b> ₹{spent:.2f}\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")

    elif call.data == "referral":
        bot.answer_callback_query(call.id)
        ref_link = f"https://t.me/{bot.get_me().username}?start=ref_{user_id}"
        bot.send_message(call.message.chat.id, f"🎁 <b>REFER & EARN PROGRAM</b>\n━━━━━━━━━━━━━━━━━━━\nInvite friends and earn <b>₹5.00</b> when they join!\n\n🔗 <b>Your Link:</b>\n<code>{ref_link}</code>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")

    elif call.data == "redeem_menu":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🎟️ <b>Send your Promo / Coupon Code:</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_coupon_redemption)

    elif call.data == "add_funds":
        bot.answer_callback_query(call.id)
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("✨ Proceed to QR Payment", callback_data="start_qr_session"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
        )
        bot.send_message(call.message.chat.id, f"💳 <b>ADD FUNDS TO WALLET</b>\n━━━━━━━━━━━━━━━━━━━\nClick below to generate your secure payment QR session.\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML", reply_markup=markup)

    elif call.data == "start_qr_session":
        bot.answer_callback_query(call.id)
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton("✅ I Have Paid (Send UTR / Proof)", callback_data="submit_proof"))
        payment_text = (
            f"💳 <b>SECURE PAYMENT GATEWAY</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👉 <b>UPI ID:</b> <code>{UPI_ID}</code>\n"
            f"⏳ <b>Status:</b> Active\n\n"
            f"1️⃣ Scan QR & pay exact amount (Min ₹30).\n"
            f"2️⃣ Click below to submit proof.\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Owner:</b> {OWNER_HANDLE}"
        )
        bot.send_photo(call.message.chat.id, QR_CODE_IMAGE_URL, caption=payment_text, parse_mode="HTML", reply_markup=markup)

    elif call.data == "submit_proof":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "📤 <b>Send your UTR / Transaction ID or screenshot:</b>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_payment_proof)

    elif call.data == "my_orders":
        bot.answer_callback_query(call.id)
        conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT order_id, smm_order_id, service_name, quantity, status FROM orders WHERE user_id = ? ORDER BY order_id DESC LIMIT 5", (user_id,))
        orders = cursor.fetchall()
        conn.close()
        if not orders:
            bot.send_message(call.message.chat.id, f"📦 <b>No orders placed yet!</b>\n\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
        else:
            orders_text = "📦 <b>YOUR RECENT ORDERS</b>\n━━━━━━━━━━━━━━━━━━━\n\n"
            markup = InlineKeyboardMarkup(row_width=1)
            for ord in orders:
                orders_text += f"🔹 <b>DB ID:</b> {ord[0]} | 📌 <b>Service:</b> {ord[2]}\n🔢 <b>Qty:</b> {ord[3]} | 📊 <b>Status:</b> <b>{ord[4]}</b>\n━━━━━━━━━━━━━━━━━━━\n"
                markup.add(InlineKeyboardButton(f"🔄 Check Status (ID: {ord[0]})", callback_data=f"chk_{ord[1]}"))
            orders_text += f"\n👤 <b>Owner:</b> {OWNER_HANDLE}"
            bot.send_message(call.message.chat.id, orders_text, parse_mode="HTML", reply_markup=markup)

    elif call.data.startswith("chk_"):
        bot.answer_callback_query(call.id)
        smm_id = call.data.split("_")[1]
        try:
            res = requests.post(SMMRAJA_API_URL, data={"key": SMMRAJA_API_KEY, "action": "status", "order": smm_id}, timeout=10).json()
            if "status" in res:
                bot.send_message(call.message.chat.id, f"📊 <b>STATUS REPORT</b>\n━━━━━━━━━━━━━━━━━━━\n🆔 <b>ID:</b> {smm_id}\n📌 <b>Status:</b> <b>{res['status']}</b>\n💰 <b>Charge:</b> ${res.get('charge', '0')}\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
            else:
                bot.send_message(call.message.chat.id, "❌ Could not fetch status.", parse_mode="HTML")
        except:
            bot.send_message(call.message.chat.id, "❌ API error.", parse_mode="HTML")

    elif call.data == "new_order":
        bot.answer_callback_query(call.id)
        services = get_cached_services()
        if services:
            user_data[user_id] = {"all_services": services}
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("📸 Instagram", callback_data="plat_instagram"),
                InlineKeyboardButton("📘 Facebook", callback_data="plat_facebook"),
                InlineKeyboardButton("▶️ YouTube", callback_data="plat_youtube"),
                InlineKeyboardButton("📢 Telegram", callback_data="plat_telegram"),
                InlineKeyboardButton("👻 Snapchat", callback_data="plat_snapchat")
            )
            markup.add(InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu"))
            bot.send_message(call.message.chat.id, f"🌐 <b>CHOOSE A PLATFORM:</b>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML", reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, "❌ Failed to fetch services from SMM API. Try again later.", parse_mode="HTML")

    elif call.data.startswith("plat_"):
        bot.answer_callback_query(call.id)
        platform = call.data.replace("plat_", "")
        all_services = user_data.get(user_id, {}).get("all_services", get_cached_services())
        markup = InlineKeyboardMarkup(row_width=1)
        count = 0
        for s in all_services:
            cat_lower = s.get("category", "").lower()
            name_lower = s.get("name", "").lower()
            matched = False
            if platform == "instagram":
                if any(kw in cat_lower or kw in name_lower for kw in ["instagram", "ig", "insta"]):
                    matched = True
            else:
                if platform in cat_lower or platform in name_lower:
                    matched = True
            if matched:
                s_id = s.get("service")
                s_name = s.get("name")
                rate_usd = s.get("rate")
                selling_rate_inr = calculate_selling_rate(rate_usd)
                markup.add(InlineKeyboardButton(f"🔹 {s_name[:40]} (₹{selling_rate_inr}/K)", callback_data=f"srvsel_{s_id}"))
                count += 1
                if count >= 45:
                    break
        if count == 0:
            bot.send_message(call.message.chat.id, f"❌ No services found for {platform}.", parse_mode="HTML")
            return
        markup.add(InlineKeyboardButton("🔙 Back to Platforms", callback_data="new_order"))
        bot.send_message(call.message.chat.id, f"📌 <b>{platform.upper()} SERVICES:</b>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML", reply_markup=markup)

    elif call.data.startswith("srvsel_"):
        bot.answer_callback_query(call.id)
        service_id = call.data.replace("srvsel_", "")
        all_services = user_data.get(user_id, {}).get("all_services", get_cached_services())
        selected_service = next((s for s in all_services if str(s.get("service")) == str(service_id)), None)
        if selected_service:
            selected_service["selling_rate"] = calculate_selling_rate(selected_service["rate"])
            if user_id not in user_data:
                user_data[user_id] = {}
            user_data[user_id]["selected_service"] = selected_service
            msg = bot.send_message(call.message.chat.id, f"🔗 <b>Send your target link for:</b>\n<i>{selected_service['name']}</i>\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
            bot.register_next_step_handler(msg, get_link_dynamic)
        else:
            bot.send_message(call.message.chat.id, "❌ Session expired. Type /start", parse_mode="HTML")

    elif call.data.startswith("approve_"):
        try:
            parts = call.data.split("_")
            target_user_id, amount = int(parts[1]), float(parts[2])
            conn = sqlite3.connect("smm_bot.db", check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_user_id))
            conn.commit()
            conn.close()
            bot.answer_callback_query(call.id, f"✅ Approved! ₹{amount} added.")
            if call.message.caption:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"{call.message.caption}\n\n<b>STATUS: APPROVED ✅ (Added ₹{amount})</b>", parse_mode="HTML", reply_markup=None)
            else:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n\n<b>STATUS: APPROVED ✅ (Added ₹{amount})</b>", parse_mode="HTML", reply_markup=None)
            bot.send_message(target_user_id, f"🎉 <b>Your payment of ₹{amount} has been added to your wallet!</b>\n\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

    elif call.data.startswith("reject_"):
        try:
            target_user_id = int(call.data.split("_")[1])
            bot.answer_callback_query(call.id, "❌ Rejected.")
            if call.message.caption:
                bot.edit_message_caption(chat_id=call.message.chat.id, message_id=call.message.message_id, caption=f"{call.message.caption}\n\n<b>STATUS: REJECTED ❌</b>", parse_mode="HTML", reply_markup=None)
            else:
                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{call.message.text}\n\n<b>STATUS: REJECTED ❌</b>", parse_mode="HTML", reply_markup=None)
            bot.send_message(target_user_id, f"❌ <b>Your payment submission was rejected by Admin.</b>\n\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML")
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ Error: {str(e)}", show_alert=True)

    elif call.data == "main_menu":
        bot.answer_callback_query(call.id)
        balance, _ = get_or_create_user(user_id, username)
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🛒 New Order", callback_data="new_order"),
            InlineKeyboardButton("💳 Add Funds", callback_data="add_funds"),
            InlineKeyboardButton("👤 My Account", callback_data="account"),
            InlineKeyboardButton("📦 My Orders", callback_data="my_orders"),
            InlineKeyboardButton("🎁 Refer & Earn", callback_data="referral"),
            InlineKeyboardButton("🎟️ Redeem Coupon", callback_data="redeem_menu")
        )
        bot.send_message(call.message.chat.id, f"🌟 <b>WELCOME TO FAST SMM PANEL</b> 🌟\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Name:</b> {call.from_user.first_name}\n🆔 <b>ID:</b> <code>{user_id}</code>\n💰 <b>Balance:</b> ₹{balance:.2f}\n━━━━━━━━━━━━━━━━━━━\n👤 <b>Owner:</b> {OWNER_HANDLE}", parse_mode="HTML", reply_markup=markup)

bot.infinity_polling()
