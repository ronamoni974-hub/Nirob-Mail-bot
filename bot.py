import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from mailtd import MailTD
import requests
import time
import threading
import re
import random
import string
import html
import os
import copy
from flask import Flask
from datetime import datetime

# --- Firebase Admin Initialization ---
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

try:
    cred = credentials.Certificate("firebase-admin-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase Connected Successfully!")
except Exception as e:
    print(f"⚠️ Firebase Setup Error: {e}")
    db = None

# --- Configuration ---
TOKEN = '8688859763:AAEzMMeHndHK8fywCOuFYuLYHeTMxI21MLM'
bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
ADMIN_ID = "8652060017"
CHANNEL_USERNAME = "@caption_only63" # ⚠️ এখানে আপনার চ্যানেলের ইউজারনেম দিন

# --- Global Storage (Hybrid Memory) ---
user_data = {}
banned_users = set()
bot_stats = {'total_mails_generated': 0}
system_data = {'active_promos': {}}

api_data = {
    'tokens': [
        'td_771bb735f2e3af99122852ce36ead823b49e36e5057843fa87fa84feb928ffce', 
        'td_c9af80675aa7a0ca3e255c9070555ab0c598578611e573c8ecd2e9ad0e5dff23', 
        'td_ef6c7eb259c1db04e66274891988f4035c7b89c23e6b35410359973e73be8e3b',  
        'td_ef6c7eb259c1db04e66274891988f4035c7b89c23e6b35410359973e73be8e3b'  
    ],
    'active_idx': 0,
    'usage': {},
    'exhausted': {}
}
api_clients = {}

# --- Firebase Sync Functions ---
def save_system_data():
    if not db: return
    try:
        db.collection('system').document('api_data').set(api_data)
        db.collection('system').document('banned_users').set({'users': list(banned_users)})
        db.collection('system').document('bot_stats').set(bot_stats)
    except Exception as e:
        print(f"Firebase System Save Error: {e}")

def save_user_data(chat_id):
    if not db: return
    try:
        data_to_save = copy.deepcopy(user_data[str(chat_id)])
        for acc in data_to_save.get('accounts', []):
            acc['seen_msgs'] = list(acc.get('seen_msgs', []))
        db.collection('users').document(str(chat_id)).set(data_to_save)
    except Exception as e:
        print(f"Firebase User Save Error: {e}")

def load_all_data_from_firebase():
    global api_data, banned_users, bot_stats, user_data
    if not db: return
    try:
        print("⏳ Loading data from Firebase...")
        api_doc = db.collection('system').document('api_data').get()
        if api_doc.exists: api_data.update(api_doc.to_dict())
        
        ban_doc = db.collection('system').document('banned_users').get()
        if ban_doc.exists: banned_users = set(ban_doc.to_dict().get('users', []))
        
        stat_doc = db.collection('system').document('bot_stats').get()
        if stat_doc.exists: bot_stats.update(stat_doc.to_dict())
        
        users_ref = db.collection('users').stream()
        for doc in users_ref:
            uid = doc.id
            u_data = doc.to_dict()
            for acc in u_data.get('accounts', []):
                acc['seen_msgs'] = set(acc.get('seen_msgs', []))
            user_data[uid] = u_data
        print("✅ Data Loading Complete!")
    except Exception as e:
        print(f"Firebase Load Error: {e}")

# --- API Management & Fallback Logic ---
def restore_apis():
    current_time = time.time()
    changed = False
    for token, exhaust_time in list(api_data['exhausted'].items()):
        if (current_time - exhaust_time) >= 30 * 86400: # 30 Days
            del api_data['exhausted'][token]
            api_data['usage'][token] = 0
            changed = True
    if changed: save_system_data()

def mark_api_exhausted(token):
    if token not in api_data['exhausted']:
        api_data['exhausted'][token] = time.time()
        api_data['usage'][token] = 1000
        save_system_data()
        try: bot.send_message(ADMIN_ID, f"⚠️ <b>API Limit Reached!</b>\n\nএকটি API এর লিমিট শেষ। পরবর্তী API তে সুইচ করা হচ্ছে।")
        except: pass

def get_active_client():
    restore_apis()
    valid_tokens = [t for t in api_data['tokens'] if "YOUR_" not in t and len(t) > 15]
    if not valid_tokens: raise Exception("All APIs Exhausted")

    for _ in range(len(valid_tokens)):
        token = valid_tokens[api_data['active_idx'] % len(valid_tokens)]
        if token not in api_data['exhausted']:
            if token not in api_clients:
                api_clients[token] = MailTD(token)
            return api_clients[token], token
        api_data['active_idx'] = (api_data['active_idx'] + 1) % len(valid_tokens)
    
    raise Exception("All APIs Exhausted")

def create_mail_with_fallback(clean_name=None):
    # 1. Try Mail.td APIs
    try:
        client, token = get_active_client()
        if api_data['usage'].get(token, 0) < 1000:
            domains = client.accounts.list_domains()
            domain_name = domains[0].domain if hasattr(domains[0], 'domain') else domains[0]
            
            email_address = f"{clean_name}@{domain_name}" if clean_name else f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}@{domain_name}"
            account = client.accounts.create(email_address, password="propassword123")
            return account.id, account.address, token 
        else:
            mark_api_exhausted(token)
    except Exception as e:
        error_msg = str(e).lower()
        if clean_name and ("already exists" in error_msg or "taken" in error_msg or "400" in error_msg):
            raise Exception("NameTaken")

    # 2. Ultimate Fallback to 1secmail if Mail.td fails
    try:
        domain_name = "1secmail.com" 
        email_address = f"{clean_name}@{domain_name}" if clean_name else f"{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}@{domain_name}"
        return "1secmail_acc", email_address, "1secmail_fallback"
    except Exception:
        raise Exception("API Error")

# --- Web Server ---
app = Flask('')
@app.route('/')
def home(): return "Pro Mail Bot is Running 24/7!"
def run_web_server(): app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

# --- Menus ---
def get_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("✨ New Pro Mail"))
    markup.row(KeyboardButton("✏️ Custom Mail"), KeyboardButton("🏠 Dashboard"))
    markup.row(KeyboardButton("🗑️ Delete Active"), KeyboardButton("👤 Profile"))
    markup.row(KeyboardButton("⚡ About Bot"))
    if str(chat_id) == ADMIN_ID: markup.row(KeyboardButton("⚙️ Admin Panel"))
    return markup

def get_admin_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("👥 User List", callback_data="admin_users"),
               InlineKeyboardButton("📊 Statistics", callback_data="admin_stats"))
    markup.add(InlineKeyboardButton("🔑 Manage APIs", callback_data="admin_apis"),
               InlineKeyboardButton("📢 Send Notice", callback_data="admin_send_promo"))
    markup.add(InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban"),
               InlineKeyboardButton("✅ Unban User", callback_data="admin_unban"))
    markup.add(InlineKeyboardButton("🗑️ Del Promo", callback_data="admin_del_promo"))
    return markup

def get_back_button():
    return InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_back"))

# --- Helper Functions ---
def is_banned(chat_id):
    if str(chat_id) in banned_users:
        bot.send_message(chat_id, "🚫 <b>Account Banned!</b>\n\nআপনি বট ব্যবহারের নিয়ম ভঙ্গ করেছেন।\nযোগাযোগ করুন: <a href='https://t.me/Ad_Walid'>@Ad_Walid</a>", disable_web_page_preview=True)
        return True
    return False

def check_membership(user_id):
    if CHANNEL_USERNAME == "@your_channel_username" or CHANNEL_USERNAME == "":
        return True 
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except Exception:
        return False

def force_sub_markup():
    markup = InlineKeyboardMarkup()
    channel_link = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
    markup.add(InlineKeyboardButton("📢 Join Channel", url=channel_link))
    markup.add(InlineKeyboardButton("✅ Verify", callback_data="verify_join"))
    return markup

def get_service_logo(sender):
    s = str(sender).lower()
    if 'facebook' in s or 'fb' in s: return '📘 Facebook'
    if 'instagram' in s or 'ig' in s: return '📸 Instagram'
    if 'google' in s or 'gmail' in s: return '🇬 Google'
    if 'tiktok' in s: return '🎵 TikTok'
    if 'netflix' in s: return '🎬 Netflix'
    return '🌐 Web Service'

def extract_and_format(subject, text_body, html_body=""):
    subject_text = subject if subject else "No Subject"
    clean_text = str(text_body) if text_body else ""
    clean_html = ""
    if html_body:
        clean_html = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'<(script|style).*?>.*?</\1>', ' ', str(html_body), flags=re.IGNORECASE | re.DOTALL))).strip()
    
    search_text = f"{subject_text} {clean_text} {clean_html}"
    otp_match = re.search(r'\b(\d{4,8})\b', search_text)
    otp_section = f"🔑 <b>Verification Code :</b> <code>{otp_match.group(1)}</code>\n\n" if otp_match else ""
    link_match = re.search(r'(https?://[^\s\"\'<>]+)', search_text)
    extracted_link = link_match.group(1) if link_match else None
    
    display_body = clean_text.strip()
    if len(display_body) < 15 and clean_html: display_body = clean_html
    if not display_body: display_body = "No Content"
    return otp_section, re.sub(r'\b(\d{4,8})\b', r'<code>\1</code>', html.escape(display_body)), extracted_link

def generate_mail_layout(email_address):
    layout = f"✅ <b>Mail Assigned Successfully !</b>\n\n📧 <b>Address :</b> <code>{email_address}</code>\n\n📡 <b>Status :</b> Live Sync Active\n\n<blockquote>•  Waiting for new messages ⬇️</blockquote>"
    markup = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("🔄 Switch Mail", callback_data="quick_switch"), InlineKeyboardButton("🔄 Force Fetch", callback_data="force_fetch"))
    return layout, markup

# --- Auto Checker Engine ---
def auto_check_mail():
    while True:
        try:
            for chat_id, data in list(user_data.items()):
                if str(chat_id) in banned_users: continue
                
                active_index = data.get('active_index', -1)
                if active_index >= 0 and data['accounts']:
                    account = data['accounts'][active_index]
                    acc_token = account.get('api_token', '')
                    email_addr = account['email']
                    needs_sync = False
                    
                    if acc_token == "1secmail_fallback":
                        login, domain = email_addr.split('@')
                        resp = requests.get(f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}").json()
                        for msg_preview in resp:
                            msg_id = msg_preview['id']
                            if msg_id not in account['seen_msgs']:
                                account['seen_msgs'].add(msg_id)
                                needs_sync = True
                                full_msg = requests.get(f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}").json()
                                otp_section, smart_body, verify_link = extract_and_format(full_msg.get('subject', ''), full_msg.get('textBody', ''), full_msg.get('htmlBody', ''))
                                mail_alert = f"✅ <b>New Message !</b>\n\n🏢 <b>From :</b> {get_service_logo(full_msg.get('from', ''))}\n📧 <b>To :</b> <code>{email_addr}</code>\n\n{otp_section}<blockquote>💬 {smart_body[:500]}...</blockquote>"
                                markup = InlineKeyboardMarkup()
                                if verify_link: markup.add(InlineKeyboardButton("🔗 Open Link", url=verify_link))
                                sent_msg = bot.send_message(chat_id, mail_alert, reply_markup=markup)
                                account['msg_ids'].append(sent_msg.message_id)
                    else:
                        account_id = account['account_id']
                        if "YOUR_" in acc_token or not acc_token: _, acc_token = get_active_client()
                        if acc_token not in api_clients: api_clients[acc_token] = MailTD(acc_token)
                        temp_client = api_clients[acc_token]
                        
                        messages, _ = temp_client.messages.list(account_id)
                        for msg_preview in messages:
                            msg_id = msg_preview.id
                            if msg_id not in account['seen_msgs']:
                                account['seen_msgs'].add(msg_id)
                                needs_sync = True
                                full_msg = temp_client.messages.get(account_id, msg_id)
                                otp_section, smart_body, verify_link = extract_and_format(full_msg.subject, getattr(full_msg, 'text_body', ''), getattr(full_msg, 'html_body', ''))
                                mail_alert = f"✅ <b>New Message !</b>\n\n🏢 <b>From :</b> {get_service_logo(getattr(full_msg, 'from_address', getattr(full_msg, 'sender', '')))}\n📧 <b>To :</b> <code>{email_addr}</code>\n\n{otp_section}<blockquote>💬 {smart_body[:500]}...</blockquote>"
                                markup = InlineKeyboardMarkup()
                                if verify_link: markup.add(InlineKeyboardButton("🔗 Open Link", url=verify_link))
                                sent_msg = bot.send_message(chat_id, mail_alert, reply_markup=markup)
                                account['msg_ids'].append(sent_msg.message_id)
                    
                    if needs_sync: save_user_data(chat_id)
        except Exception: pass
        time.sleep(3)

# --- Init User ---
def init_user(message):
    chat_id = str(message.chat.id)
    if chat_id not in user_data:
        user_data[chat_id] = {'accounts': [], 'active_index': -1, 'total_generated': 0, 'name': message.from_user.first_name or "Unknown", 'username': f"@{message.from_user.username}" if message.from_user.username else "N/A", 'joined': datetime.now().strftime("%Y-%m-%d"), 'custom_mail_msgs': []}
        save_user_data(chat_id)

# --- Bot Handlers ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    init_user(message)
    if is_banned(message.chat.id): return
    
    if not check_membership(message.from_user.id):
        bot.send_message(
            message.chat.id, 
            "⚠️ <b>বটটি ব্যবহার করতে আমাদের টেলিগ্রাম চ্যানেলে জয়েন করুন!</b>\n\nচ্যানেলে জয়েন করার পর নিচের <b>Verify</b> বাটনে ক্লিক করুন।", 
            reply_markup=force_sub_markup()
        )
        return

    bot.send_message(message.chat.id, "🌟 <b>Welcome to Pro Mail Assistant!</b>\n\nআপনার পার্সোনাল ইনবক্সকে স্প্যাম থেকে সুরক্ষিত রাখুন।", reply_markup=get_main_menu(str(message.chat.id)))

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = str(message.chat.id)
    text = message.text
    init_user(message)
    if is_banned(chat_id): return
    
    if not check_membership(message.from_user.id):
        bot.send_message(
            message.chat.id, 
            "⚠️ <b>বটটি ব্যবহার করতে আগে আমাদের চ্যানেলে জয়েন করুন!</b>", 
            reply_markup=force_sub_markup()
        )
        return

    if text == "✨ New Pro Mail":
        anim_msg = bot.send_message(chat_id, "<i>⏳ Initializing Protocol...</i>")
        try:
            acc_id, email_addr, used_token = create_mail_with_fallback() 
            if used_token != "1secmail_fallback":
                api_data['usage'][used_token] = api_data['usage'].get(used_token, 0) + 1
                
            user_data[chat_id]['accounts'].append({'account_id': acc_id, 'email': email_addr, 'seen_msgs': set(), 'msg_ids': [anim_msg.message_id], 'api_token': used_token})
            user_data[chat_id]['active_index'] = len(user_data[chat_id]['accounts']) - 1
            user_data[chat_id]['total_generated'] += 1
            bot_stats['total_mails_generated'] += 1
            
            layout, markup = generate_mail_layout(email_addr)
            bot.edit_message_text(layout, chat_id, anim_msg.message_id, reply_markup=markup)
            
            save_user_data(chat_id)
            save_system_data()
        except Exception as e:
            bot.edit_message_text(f"❌ Error Details: {str(e)}", chat_id, anim_msg.message_id)

    elif text == "✏️ Custom Mail":
        msg = bot.send_message(chat_id, "✏️ <b>Custom Mail Creation</b>\n\nমেইলের শুরুতে কী নাম দিতে চান লিখুন:", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_custom")))
        user_data[chat_id]['custom_mail_msgs'] = [message.message_id, msg.message_id]
        save_user_data(chat_id)
        bot.register_next_step_handler(msg, process_custom_mail)

    elif text == "🏠 Dashboard":
        accounts = user_data[chat_id]['accounts']
        if not accounts: bot.send_message(chat_id, "⚠️ আপনার কোনো অ্যাক্টিভ মেইল নেই।")
        else:
            dash_text = "🗂️ <b>Your Mail Dashboard</b>\n\n"
            markup = InlineKeyboardMarkup(row_width=1)
            for i, acc in enumerate(accounts):
                status = "🟢 Active" if i == user_data[chat_id]['active_index'] else "⚪ Standby"
                dash_text += f"{i+1}. <code>{acc['email']}</code> [{status}]\n\n"
                markup.add(InlineKeyboardButton(f"🔄 Switch to Mail {i+1}", callback_data=f"switch_{i}"))
            bot.send_message(chat_id, dash_text, reply_markup=markup)

    elif text == "🗑️ Delete Active":
        if user_data[chat_id]['accounts']:
            active_idx = user_data[chat_id]['active_index']
            del_mail = user_data[chat_id]['accounts'].pop(active_idx)
            for msg_id in del_mail['msg_ids']:
                try: bot.delete_message(chat_id, msg_id)
                except: pass
            user_data[chat_id]['active_index'] = 0 if user_data[chat_id]['accounts'] else -1
            bot.send_message(chat_id, f"✅ <b>Deleted !</b>\n\nমেইল <code>{del_mail['email']}</code> চ্যাট থেকে মুছে ফেলা হয়েছে।", reply_markup=get_main_menu(chat_id))
            save_user_data(chat_id)
        else: bot.send_message(chat_id, "⚠️ ডিলেট করার মতো মেইল নেই।")

    elif text == "👤 Profile":
        ui = user_data[chat_id]
        bot.send_message(chat_id, f"👤 <b>User Profile</b>\n\n📛 <b>Name :</b> {ui['name']}\n🆔 <b>User ID :</b> <code>{chat_id}</code>\n📊 <b>Total Generated :</b> {ui['total_generated']} Mails\n🟢 <b>Current Active :</b> {len(ui['accounts'])} Mails")

    elif text == "⚡ About Bot":
        about_text = (
            "🚀 <b>Premium Temp Mail Bot</b>\n\n"
            "• Engine: Mail.td Pro API & Ultimate Fallback\n"
            "• Performance: Zero-Lag Sync\n"
            "• Developer: <a href='https://t.me/Ad_Walid'>Md Walid</a>\n"
            "• Bot Admin: <a href='https://t.me/nirob_owner4'>Owner Nirob</a>\n\n"
            "<i>Crafted with modern interface aesthetics.</i>"
        )
        bot.send_message(chat_id, about_text, disable_web_page_preview=True)

    elif text == "⚙️ Admin Panel" and chat_id == ADMIN_ID:
        bot.send_message(chat_id, "⚙️ <b>Admin Control Panel</b>\n\nবেছে নিন আপনি কী করতে চান:", reply_markup=get_admin_menu())

def process_custom_mail(message):
    chat_id = str(message.chat.id)
    if message.text.startswith('/'): return
    
    clean_name = re.sub(r'[^a-z0-9]', '', message.text.lower().strip())
    if len(clean_name) < 3:
        msg = bot.send_message(chat_id, "⚠️ নাম কমপক্ষে ৩ অক্ষরের হতে হবে। আবার দিন:")
        bot.register_next_step_handler(msg, process_custom_mail)
        return
        
    anim_msg = bot.send_message(chat_id, "<i>⏳ Checking availability...</i>")
    try:
        acc_id, email_addr, used_token = create_mail_with_fallback(clean_name)
        if used_token != "1secmail_fallback": api_data['usage'][used_token] = api_data['usage'].get(used_token, 0) + 1
            
        user_data[chat_id]['accounts'].append({'account_id': acc_id, 'email': email_addr, 'seen_msgs': set(), 'msg_ids': [], 'api_token': used_token})
        user_data[chat_id]['active_index'] = len(user_data[chat_id]['accounts']) - 1
        user_data[chat_id]['total_generated'] += 1
        bot_stats['total_mails_generated'] += 1
        
        for msg_id in user_data[chat_id].get('custom_mail_msgs', []):
            try: bot.delete_message(chat_id, msg_id)
            except: pass
        user_data[chat_id]['custom_mail_msgs'] = []
        
        layout, markup = generate_mail_layout(email_addr)
        bot.edit_message_text(layout, chat_id, anim_msg.message_id, reply_markup=markup)
        user_data[chat_id]['accounts'][-1]['msg_ids'].append(anim_msg.message_id)
        
        save_user_data(chat_id)
        save_system_data()
    except Exception as e:
        if str(e) == "NameTaken":
            bot.delete_message(chat_id, anim_msg.message_id)
            msg = bot.send_message(chat_id, f"❌ <b>দুঃখিত!</b> <code>{clean_name}</code> নামটি আগে থেকেই কেউ নিয়ে নিয়েছে। অন্য কোনো নাম দিন:", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("❌ Cancel", callback_data="cancel_custom")))
            user_data[chat_id]['custom_mail_msgs'].append(msg.message_id)
            save_user_data(chat_id)
            bot.register_next_step_handler(msg, process_custom_mail)
        else:
            bot.edit_message_text(f"❌ Error Details: {str(e)}", chat_id, anim_msg.message_id)

# --- Admin Processing Functions ---
def process_add_api(message):
    new_token = message.text.strip()
    if len(new_token) > 20: 
        if new_token not in api_data['tokens']:
            api_data['tokens'].append(new_token)
            save_system_data()
            bot.send_message(message.chat.id, f"✅ <b>API Added Successfully!</b>\n\nমোট API সংখ্যা এখন: {len(api_data['tokens'])}")
        else: bot.send_message(message.chat.id, "⚠️ এই API Token টি আগেই লিস্টে আছে।")
    else: bot.send_message(message.chat.id, "❌ ইনভ্যালিড টোকেন!")

def process_ban(message):
    if not message.text.isdigit(): return
    banned_users.add(message.text.strip())
    save_system_data()
    bot.send_message(message.chat.id, f"✅ <b>{message.text}</b> কে ব্যান করা হয়েছে!")

def process_unban(message):
    if not message.text.isdigit(): return
    banned_users.discard(message.text.strip())
    save_system_data()
    bot.send_message(message.chat.id, f"✅ <b>{message.text}</b> কে আনব্যান করা হয়েছে!")

def process_promo_text(message):
    if not message.text: return
    promo_text = message.text
    msg = bot.send_message(message.chat.id, "🔗 লিংকের জন্য বাটন দিতে চাইলে লিংক দিন। না দিতে চাইলে 'no' লিখুন:")
    bot.register_next_step_handler(msg, lambda m: broadcast_promo(m, promo_text))

def broadcast_promo(message, promo_text):
    link = message.text.strip()
    markup = InlineKeyboardMarkup()
    if link.lower() != 'no' and link.startswith('http'): markup.add(InlineKeyboardButton("🌟 View Details", url=link))
    bot.send_message(message.chat.id, "🚀 ব্রডকাস্ট শুরু হয়েছে... এটি ব্যাকগ্রাউন্ডে চলবে।")
    def send_to_all():
        system_data['active_promos'].clear()
        for uid in list(user_data.keys()):
            try:
                sent = bot.send_message(uid, f"📢 <b>Official Update</b>\n\n{promo_text}", reply_markup=markup if markup.keyboard else None)
                system_data['active_promos'][uid] = sent.message_id
            except: pass
            time.sleep(0.05)
    threading.Thread(target=send_to_all, daemon=True).start()

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = str(call.message.chat.id)
    if is_banned(chat_id): return
    
    if call.data == "verify_join":
        if check_membership(call.from_user.id):
            bot.delete_message(chat_id, call.message.message_id)
            bot.send_message(chat_id, "🌟 <b>Welcome to Pro Mail Assistant!</b>\n\nআপনার পার্সোনাল ইনবক্সকে স্প্যাম থেকে সুরক্ষিত রাখুন।", reply_markup=get_main_menu(chat_id))
        else:
            bot.answer_callback_query(call.id, "⚠️ আপনি এখনো চ্যানেলে জয়েন করেননি! আগে জয়েন করুন।", show_alert=True)
            
    elif call.data == "cancel_custom":
        bot.clear_step_handler_by_chat_id(call.message.chat.id)
        for msg_id in user_data.get(chat_id, {}).get('custom_mail_msgs', []):
            try: bot.delete_message(chat_id, msg_id)
            except: pass
        user_data[chat_id]['custom_mail_msgs'] = []
        save_user_data(chat_id)
        bot.send_message(chat_id, "❌ Custom Mail creation cancelled.", reply_markup=get_main_menu(chat_id))

    elif call.data == "force_fetch":
        bot.answer_callback_query(call.id, "🔄 Fetching new emails from server...")

    elif call.data == "quick_switch":
        accounts = user_data.get(chat_id, {}).get('accounts', [])
        if len(accounts) > 1: bot.answer_callback_query(call.id, "Please use Dashboard to switch mails.")
        else: bot.answer_callback_query(call.id, "You only have one active mail.")

    elif call.data.startswith('switch_'):
        idx = int(call.data.split('_')[1])
        if idx < len(user_data.get(chat_id, {}).get('accounts', [])):
            user_data[chat_id]['active_index'] = idx
            bot.answer_callback_query(call.id, "Switched successfully!")
            layout, markup = generate_mail_layout(user_data[chat_id]['accounts'][idx]['email'])
            bot.edit_message_text(layout, chat_id, call.message.message_id, reply_markup=markup)
            save_user_data(chat_id)
            
    elif chat_id == ADMIN_ID:
        if call.data == "admin_back":
            bot.edit_message_text("⚙️ <b>Admin Control Panel</b>\n\nবেছে নিন আপনি কী করতে চান:", chat_id, call.message.message_id, reply_markup=get_admin_menu())
            
        elif call.data == "admin_apis":
            restore_apis()
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("➕ Add New API Token", callback_data="admin_add_api"))
            markup.add(InlineKeyboardButton("🔙 Back to Panel", callback_data="admin_back"))
            
            api_info = f"🔑 <b>API Limit Management</b>\n\n"
            for i, token in enumerate(api_data['tokens']):
                usage = api_data['usage'].get(token, 0)
                status = "🟢 Active"
                if token in api_data['exhausted']:
                    days_left = 30 - (datetime.now() - datetime.fromtimestamp(api_data['exhausted'][token])).days
                    status = f"🔴 Exhausted (Resets in {days_left}d)"
                elif i == api_data['active_idx']: status = "🔵 Currently Using"
                
                short_token = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else token
                api_info += f"<b>{i+1}.</b> <code>{short_token}</code>\n└ Ops: <b>{usage} / 1000</b> | {status}\n\n"
            api_info += f"<i>💡 নোট: সকল API লিমিট শেষ হলে বট অটোমেটিক 1secmail (.com) সার্ভারে সুইচ করবে!</i>"
            bot.edit_message_text(api_info, chat_id, call.message.message_id, reply_markup=markup)
            
        elif call.data == "admin_add_api":
            bot.edit_message_text("➕ <b>Add New API Token</b>\n\nআপনার নতুন API Token টি টাইপ করে সেন্ড করুন:", chat_id, call.message.message_id, reply_markup=get_back_button())
            bot.register_next_step_handler(call.message, process_add_api)
            
        elif call.data == "admin_stats":
            total_users = len(user_data)
            active_accounts = sum(len(d.get('accounts', [])) for d in user_data.values())
            stats = f"📊 <b>Bot Live Statistics</b>\n\n👥 Total Users: <b>{total_users}</b>\n\n🚫 Banned Users: <b>{len(banned_users)}</b>\n\n📧 Total Mails Gen: <b>{bot_stats['total_mails_generated']}</b>\n\n🟢 Current Active Mails: <b>{active_accounts}</b>"
            bot.edit_message_text(stats, chat_id, call.message.message_id, reply_markup=get_back_button())
            
        elif call.data == "admin_users":
            user_list = "👥 <b>Recent Users List:</b>\n\n"
            for uid, data in list(user_data.items())[-20:]:
                user_list += f"• {data.get('name', 'Unknown')} (<code>{uid}</code>) - <b>{data.get('total_generated', 0)} Mails</b>\n"
            bot.edit_message_text(user_list, chat_id, call.message.message_id, reply_markup=get_back_button())
            
        elif call.data == "admin_ban":
            bot.edit_message_text("✍️ <b>Ban User:</b>\n\nযাকে ব্যান করতে চান তার User ID টাইপ করে সেন্ড করুন:", chat_id, call.message.message_id, reply_markup=get_back_button())
            bot.register_next_step_handler(call.message, process_ban)
            
        elif call.data == "admin_unban":
            bot.edit_message_text("✍️ <b>Unban User:</b>\n\nযাকে আনব্যান করতে চান তার User ID সেন্ড করুন:", chat_id, call.message.message_id, reply_markup=get_back_button())
            bot.register_next_step_handler(call.message, process_unban)
            
        elif call.data == "admin_send_promo":
            bot.edit_message_text("📢 <b>Broadcast Message:</b>\n\nনোটিশ বা প্রোমোশনাল পোস্টের টেক্সট লিখে সেন্ড করুন (HTML):", chat_id, call.message.message_id, reply_markup=get_back_button())
            bot.register_next_step_handler(call.message, process_promo_text)
            
        elif call.data == "admin_del_promo":
            deleted = 0
            for uid, msg_id in system_data['active_promos'].items():
                try: bot.delete_message(uid, msg_id); deleted += 1
                except: pass
            system_data['active_promos'].clear()
            bot.edit_message_text(f"✅ <b>Promo Deleted!</b>\n\n{deleted} জন ইউজারের ইনবক্স থেকে সর্বশেষ মেসেজ মুছে ফেলা হয়েছে।", chat_id, call.message.message_id, reply_markup=get_back_button())

if __name__ == "__main__":
    # --- Start Setup ---
    load_all_data_from_firebase()
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=auto_check_mail, daemon=True).start()
    print("🚀 Ultimate Fallback Bot is Live...")
    while True:
        try: bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception: time.sleep(5)
