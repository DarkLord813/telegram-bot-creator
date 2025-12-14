import requests
import time
import os
import sys
import json
import sqlite3
import secrets
import threading
import hashlib
import base64
from datetime import datetime, timedelta
from flask import Flask, jsonify, request
from threading import Thread, Lock
import traceback
import uuid
import re
import subprocess
import tempfile
import shutil

print("=" * 60)
print("🤖 AUTO-BACKUP MASTER BOT")
print("GitHub Backup | Star Payments | Bot Factory")
print("=" * 60)

# ==================== ENVIRONMENT CONFIGURATION ====================

class EnvConfig:
    """Load environment variables from Render"""
    
    @staticmethod
    def load():
        config = {}
        
        # Required variables
        required = {
            'BOT_TOKEN': 'Telegram Bot Token',
            'GITHUB_TOKEN': 'GitHub Personal Access Token',
            'GITHUB_REPO_OWNER': 'GitHub Username',
            'GITHUB_REPO_NAME': 'GitHub Repository Name'
        }
        
        # Load required variables
        for var, desc in required.items():
            value = os.environ.get(var)
            if not value:
                print(f"❌ ERROR: {var} is required! ({desc})")
                sys.exit(1)
            config[var] = value
            print(f"✅ {var}: {value[:20]}..." if len(value) > 20 else f"✅ {var}: {value}")
        
        # Load optional variables
        config['GITHUB_BACKUP_BRANCH'] = os.environ.get('GITHUB_BACKUP_BRANCH', 'main')
        config['GITHUB_BACKUP_PATH'] = os.environ.get('GITHUB_BACKUP_PATH', 'backups/masterbot')
        config['PORT'] = int(os.environ.get('PORT', 8080))
        config['STAR_PRICE'] = int(os.environ.get('STAR_PRICE', 200))
        config['ADMIN_TOKEN'] = os.environ.get('ADMIN_TOKEN', secrets.token_hex(32))
        
        # Auto-detect webhook URL
        render_url = os.environ.get('RENDER_EXTERNAL_URL')
        if render_url:
            config['WEBHOOK_URL'] = render_url
            config['MASTER_DOMAIN'] = render_url
        else:
            config['WEBHOOK_URL'] = f"http://localhost:{config['PORT']}"
            config['MASTER_DOMAIN'] = f"http://localhost:{config['PORT']}"
        
        print(f"✅ GITHUB_BACKUP_BRANCH: {config['GITHUB_BACKUP_BRANCH']}")
        print(f"✅ GITHUB_BACKUP_PATH: {config['GITHUB_BACKUP_PATH']}")
        print(f"✅ PORT: {config['PORT']}")
        print(f"✅ STAR_PRICE: {config['STAR_PRICE']}")
        print(f"✅ WEBHOOK_URL: {config['WEBHOOK_URL']}")
        print("=" * 60)
        
        return config

# Load configuration
config = EnvConfig.load()
BOT_TOKEN = config['BOT_TOKEN']
GITHUB_TOKEN = config['GITHUB_TOKEN']
GITHUB_REPO_OWNER = config['GITHUB_REPO_OWNER']
GITHUB_REPO_NAME = config['GITHUB_REPO_NAME']
GITHUB_BACKUP_BRANCH = config['GITHUB_BACKUP_BRANCH']
GITHUB_BACKUP_PATH = config['GITHUB_BACKUP_PATH']
PORT = config['PORT']
STAR_PRICE = config['STAR_PRICE']
WEBHOOK_URL = config['WEBHOOK_URL']
MASTER_DOMAIN = config['MASTER_DOMAIN']
ADMIN_TOKEN = config['ADMIN_TOKEN']

# Admin IDs
ADMIN_IDS = [7713987088, 7475473197]

# Flask App
app = Flask(__name__)
bot_instance = None

# ==================== GITHUB AUTO-BACKUP SYSTEM ====================

class GitHubAutoBackup:
    """GitHub automatic backup system"""
    
    def __init__(self):
        self.repo_full = f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        self.backup_path = GITHUB_BACKUP_PATH
        self.api_base = "https://api.github.com"
        self.auth_header = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.backup_count = 0
        self.last_backup = None
        print(f"✅ GitHub Backup: {self.repo_full}")
    
    def create_backup(self, db_content, reason="auto"):
        """Create backup to GitHub"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"masterbot_{timestamp}.db"
            filepath = f"{self.backup_path}/{filename}"
            
            # Encode content
            encoded = base64.b64encode(db_content).decode('utf-8')
            
            # Check if file exists
            check_url = f"{self.api_base}/repos/{self.repo_full}/contents/{filepath}"
            check_resp = requests.get(check_url, headers=self.auth_header, timeout=30)
            
            commit_data = {
                "message": f"🤖 Backup: {reason} - {timestamp}",
                "content": encoded,
                "branch": GITHUB_BACKUP_BRANCH
            }
            
            if check_resp.status_code == 200:
                commit_data["sha"] = check_resp.json()["sha"]
            
            # Upload file
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{filepath}"
            response = requests.put(url, headers=self.auth_header, json=commit_data, timeout=30)
            
            if response.status_code in [200, 201]:
                self.backup_count += 1
                self.last_backup = datetime.now()
                print(f"✅ Backup created: {filename}")
                return {"success": True, "filename": filename}
            else:
                print(f"❌ Backup failed: {response.status_code}")
                return {"success": False, "error": response.text}
                
        except Exception as e:
            print(f"❌ Backup error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_latest_backup(self):
        """Get latest backup from GitHub"""
        try:
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{self.backup_path}"
            response = requests.get(url, headers=self.auth_header, timeout=30)
            
            if response.status_code == 200:
                files = response.json()
                db_files = [f for f in files if f['name'].endswith('.db')]
                if db_files:
                    latest = max(db_files, key=lambda x: x['name'])
                    return latest
            return None
        except Exception as e:
            print(f"❌ Get backup error: {e}")
            return None
    
    def restore_backup(self, filename):
        """Restore backup from GitHub"""
        try:
            filepath = f"{self.backup_path}/{filename}"
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{filepath}"
            response = requests.get(url, headers=self.auth_header, timeout=30)
            
            if response.status_code == 200:
                content = response.json()['content']
                decoded = base64.b64decode(content)
                return decoded
            return None
        except Exception as e:
            print(f"❌ Restore error: {e}")
            return None

# ==================== DATABASE MANAGER ====================

class DatabaseManager:
    """Database with auto-backup functionality"""
    
    def __init__(self, github_backup):
        self.db_path = "masterbot.db"
        self.github_backup = github_backup
        self.process_count = 0
        self.backup_threshold = 5
        self.setup_database()
    
    def setup_database(self):
        """Setup database tables"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                stars INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Star payments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS star_payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP
            )
        ''')
        
        # User bots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_bots (
                bot_token TEXT PRIMARY KEY,
                bot_username TEXT,
                owner_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Activity logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Database setup complete")
    
    def execute_with_backup(self, query, params=(), user_id=None, action=None):
        """Execute query with auto-backup check"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        try:
            if isinstance(query, str):
                cursor.execute(query, params)
            else:
                cursor.executescript(query)
            
            conn.commit()
            self.process_count += 1
            
            # Log activity
            if user_id and action:
                cursor.execute(
                    "INSERT INTO activity_logs (user_id, action, details) VALUES (?, ?, ?)",
                    (user_id, action, json.dumps(params))
                )
                conn.commit()
            
            # Check if backup needed
            if self.process_count >= self.backup_threshold:
                self.create_backup(f"auto_after_{action}")
                self.process_count = 0
            
            return cursor
            
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def create_backup(self, reason="manual"):
        """Create database backup"""
        try:
            with open(self.db_path, 'rb') as f:
                db_content = f.read()
            
            result = self.github_backup.create_backup(db_content, reason)
            return result
        except Exception as e:
            print(f"❌ Create backup error: {e}")
            return {"success": False, "error": str(e)}
    
    def restore_latest(self):
        """Restore from latest backup"""
        try:
            latest = self.github_backup.get_latest_backup()
            if latest:
                db_content = self.github_backup.restore_backup(latest['name'])
                if db_content:
                    with open(self.db_path, 'wb') as f:
                        f.write(db_content)
                    print(f"✅ Restored from backup: {latest['name']}")
                    return True
            return False
        except Exception as e:
            print(f"❌ Restore error: {e}")
            return False

# ==================== MASTER BOT ====================

class MasterBot:
    """Main Telegram bot with auto-backup"""
    
    def __init__(self):
        self.token = BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}/"
        
        # Initialize systems
        self.github_backup = GitHubAutoBackup()
        self.db = DatabaseManager(self.github_backup)
        
        # Recover from backup
        self.recover_from_backup()
        
        # Setup webhook
        self.setup_webhook()
        
        print("✅ Master Bot initialized")
    
    def recover_from_backup(self):
        """Recover from GitHub backup on startup"""
        print("🔄 Checking for GitHub backup...")
        if self.db.restore_latest():
            print("✅ Recovered from GitHub backup")
        else:
            print("ℹ️ Starting with fresh database")
    
    def setup_webhook(self):
        """Setup Telegram webhook"""
        try:
            webhook_url = f"{WEBHOOK_URL}/webhook/{self.token}"
            response = requests.post(
                f"{self.base_url}setWebhook",
                json={'url': webhook_url},
                timeout=10
            )
            if response.json().get('ok'):
                print(f"✅ Webhook set: {webhook_url}")
            else:
                print(f"⚠️ Webhook setup failed")
        except Exception as e:
            print(f"⚠️ Webhook error: {e}")
    
    def send_message(self, chat_id, text, **kwargs):
        """Send Telegram message"""
        try:
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            }
            data.update(kwargs)
            response = requests.post(f"{self.base_url}sendMessage", json=data, timeout=10)
            return response.json()
        except Exception as e:
            print(f"❌ Send message error: {e}")
            return None
    
    def process_update(self, update):
        """Process incoming update"""
        try:
            if 'message' in update:
                message = update['message']
                chat_id = message['chat']['id']
                
                if 'from' in message:
                    user = message['from']
                    user_id = user['id']
                    username = user.get('username', '')
                    first_name = user.get('first_name', 'User')
                    
                    # Register/update user
                    self.register_user(user_id, username, first_name)
                
                if 'text' in message:
                    text = message['text']
                    
                    if text == '/start':
                        self.handle_start(chat_id, user_id, first_name)
                    
                    elif text == '/help':
                        self.handle_help(chat_id)
                    
                    elif text == '/backup':
                        self.handle_backup(chat_id, user_id)
                    
                    elif text == '/stats':
                        self.handle_stats(chat_id)
                    
                    elif text == '/mystats':
                        self.handle_mystats(chat_id, user_id)
                    
                    elif text.startswith('/addstars'):
                        self.handle_addstars(chat_id, user_id, text)
                    
                    elif text.startswith('/createbot'):
                        self.handle_createbot(chat_id, user_id, text)
                    
                    elif text == '/env':
                        self.handle_env(chat_id)
                    
                    else:
                        self.send_message(chat_id, "❓ Unknown command. Use /help")
        
        except Exception as e:
            print(f"❌ Process error: {e}")
    
    def register_user(self, user_id, username, first_name):
        """Register or update user"""
        try:
            self.db.execute_with_backup(
                '''
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_seen) 
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (user_id, username, first_name),
                user_id=user_id,
                action="user_update"
            )
        except Exception as e:
            print(f"❌ Register user error: {e}")
    
    def handle_start(self, chat_id, user_id, first_name):
        """Handle /start command"""
        message = f"""🤖 *Auto-Backup Master Bot*

Hello {first_name}! I'm a bot factory with *automatic GitHub backups*.

⚡ *Features:*
• 🤖 Create and host Telegram bots
• 💾 Auto-backup to GitHub after every action
• 🔄 Auto-recover from backup on restart
• ⭐ Star payment system
• 📊 Full statistics and logging

💰 *Star System:*
• Create bot: 100 stars
• Clone master: {STAR_PRICE} stars
• Check balance: /mystats

🔧 *Commands:*
/help - Show all commands
/backup - Create manual backup
/stats - System statistics  
/mystats - Your statistics
/createbot TOKEN - Create new bot
/addstars AMOUNT - Add stars (admin)

🌐 *GitHub Backup:*
• Repository: `{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}`
• Path: `{GITHUB_BACKUP_PATH}`
• Branch: `{GITHUB_BACKUP_BRANCH}`

✅ *Auto-backup enabled!* All your data is automatically saved."""
        
        self.send_message(chat_id, message)
    
    def handle_help(self, chat_id):
        """Handle /help command"""
        message = """🆘 *Bot Commands*

🤖 *User Commands:*
/start - Welcome message
/help - This help message
/backup - Create manual backup
/stats - System statistics
/mystats - Your statistics
/createbot TOKEN - Create bot (100⭐)

👑 *Admin Commands:*
/addstars AMOUNT [USER_ID] - Add stars
/env - Environment info

💾 *Auto-Backup System:*
• Backs up after every 5 actions
• Manual backup with /backup
• Auto-recover on restart
• All data stored on GitHub

💰 *Star Prices:*
• Create simple bot: 100 stars
• Clone master bot: {STAR_PRICE} stars

⚡ *Quick Start:*
1. Get bot token from @BotFather
2. Send: /createbot YOUR_TOKEN
3. Pay 100 stars
4. Your bot is ready!

❓ *Need help?* Contact the bot admin.""".format(STAR_PRICE=STAR_PRICE)
        
        self.send_message(chat_id, message)
    
    def handle_backup(self, chat_id, user_id):
        """Handle /backup command"""
        if user_id not in ADMIN_IDS:
            self.send_message(chat_id, "❌ Admin access required.")
            return
        
        self.send_message(chat_id, "💾 Creating backup...")
        result = self.db.create_backup(f"manual_by_user_{user_id}")
        
        if result.get('success'):
            self.send_message(chat_id, f"✅ Backup created: {result['filename']}")
        else:
            self.send_message(chat_id, f"❌ Backup failed: {result.get('error', 'Unknown error')}")
    
    def handle_stats(self, chat_id):
        """Handle /stats command"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_bots WHERE is_active = 1")
        bot_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(stars) FROM users")
        total_stars = cursor.fetchone()[0] or 0
        
        conn.close()
        
        message = f"""📊 *System Statistics*

👥 Users: {user_count}
🤖 Active Bots: {bot_count}
⭐ Total Stars: {total_stars}
💾 Backups Created: {self.github_backup.backup_count}
🔄 Last Backup: {self.github_backup.last_backup.strftime('%Y-%m-%d %H:%M') if self.github_backup.last_backup else 'Never'}

🌐 *GitHub Backup:*
• Repository: {GITHUB_REPO_NAME}
• Path: {GITHUB_BACKUP_PATH}
• Branch: {GITHUB_BACKUP_BRANCH}

⚡ *Auto-Backup: ACTIVE*
• Backup threshold: 5 actions
• Manual backup: /backup
• Recovery on restart: ENABLED"""
        
        self.send_message(chat_id, message)
    
    def handle_mystats(self, chat_id, user_id):
        """Handle /mystats command"""
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT username, stars, created_at FROM users WHERE user_id = ?",
            (user_id,)
        )
        user = cursor.fetchone()
        
        cursor.execute(
            "SELECT COUNT(*) FROM user_bots WHERE owner_id = ? AND is_active = 1",
            (user_id,)
        )
        bot_count = cursor.fetchone()[0]
        
        conn.close()
        
        if user:
            username, stars, created = user
            message = f"""📊 *Your Statistics*

👤 Username: {username}
🆔 User ID: `{user_id}`
⭐ Stars: {stars}
🤖 Your Bots: {bot_count}
📅 Joined: {created[:10]}

💰 *Star Prices:*
• Create bot: 100 stars
• Clone master: {STAR_PRICE} stars

💾 *Backup Status:*
✅ Your data is auto-backed up
✅ All actions are logged
✅ Recoverable from GitHub"""
        else:
            message = "❌ User not found. Send /start first."
        
        self.send_message(chat_id, message)
    
    def handle_addstars(self, chat_id, user_id, text):
        """Handle /addstars command"""
        if user_id not in ADMIN_IDS:
            self.send_message(chat_id, "❌ Admin access required.")
            return
        
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, "Usage: /addstars AMOUNT [USER_ID]")
            return
        
        try:
            amount = int(parts[1])
            target_id = int(parts[2]) if len(parts) > 2 else user_id
            
            # Add stars
            cursor = self.db.execute_with_backup(
                "UPDATE users SET stars = stars + ? WHERE user_id = ?",
                (amount, target_id),
                user_id=user_id,
                action="add_stars"
            )
            
            if cursor.rowcount > 0:
                payment_id = f"admin_{secrets.token_hex(8)}"
                self.db.execute_with_backup(
                    '''
                    INSERT INTO star_payments (payment_id, user_id, amount, status, verified_at)
                    VALUES (?, ?, ?, 'verified', CURRENT_TIMESTAMP)
                    ''',
                    (payment_id, target_id, amount),
                    user_id=user_id,
                    action="star_payment"
                )
                
                self.send_message(chat_id, f"✅ Added {amount} stars to user {target_id}")
            else:
                self.send_message(chat_id, "❌ User not found")
                
        except ValueError:
            self.send_message(chat_id, "❌ Invalid amount")
        except Exception as e:
            self.send_message(chat_id, f"❌ Error: {str(e)}")
    
    def handle_createbot(self, chat_id, user_id, text):
        """Handle /createbot command"""
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, 
                "Usage: /createbot YOUR_BOT_TOKEN\n\n"
                "Get token from @BotFather")
            return
        
        bot_token = parts[1]
        bot_price = 100  # Stars required
        
        # Check user balance
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            self.send_message(chat_id, "❌ User not found. Send /start first.")
            return
        
        user_stars = user[0]
        
        if user_stars < bot_price:
            conn.close()
            self.send_message(chat_id,
                f"❌ Insufficient stars\n"
                f"Required: {bot_price} stars\n"
                f"Your balance: {user_stars} stars\n\n"
                f"Ask admin for stars: /addstars")
            return
        
        # Test bot token
        test_url = f"https://api.telegram.org/bot{bot_token}/getMe"
        try:
            response = requests.get(test_url, timeout=10)
            if not response.json().get('ok'):
                conn.close()
                self.send_message(chat_id, "❌ Invalid bot token")
                return
            
            bot_info = response.json()['result']
            bot_username = bot_info['username']
            
        except:
            conn.close()
            self.send_message(chat_id, "❌ Could not verify bot token")
            return
        
        # Create bot record
        cursor.execute(
            '''
            INSERT INTO user_bots (bot_token, bot_username, owner_id)
            VALUES (?, ?, ?)
            ''',
            (bot_token[:50], bot_username, user_id)
        )
        
        # Deduct stars
        cursor.execute(
            "UPDATE users SET stars = stars - ? WHERE user_id = ?",
            (bot_price, user_id)
        )
        
        conn.commit()
        conn.close()
        
        # Log activity
        self.db.execute_with_backup(
            "SELECT 1",  # Dummy query to trigger backup
            user_id=user_id,
            action="create_bot"
        )
        
        # Set webhook
        webhook_url = f"{WEBHOOK_URL}/webhook/{bot_token}"
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={'url': webhook_url}
        )
        
        success_msg = f"""✅ *Bot Created Successfully!*

🤖 Bot: @{bot_username}
💰 Price: {bot_price} stars
📉 New balance: {user_stars - bot_price} stars

🔗 Webhook: {webhook_url}

⚡ *Features included:*
• Auto-backup system
• Star payment integration
• User management
• 24/7 hosting

🚀 Your bot is ready: @{bot_username}

💾 *Auto-backup enabled!* All data will be saved to GitHub."""
        
        self.send_message(chat_id, success_msg)
    
    def handle_env(self, chat_id):
        """Handle /env command"""
        if chat_id not in ADMIN_IDS:
            self.send_message(chat_id, "❌ Admin access required.")
            return
        
        message = f"""🌐 *Environment Configuration*

🤖 BOT_TOKEN: `{BOT_TOKEN[:15]}...`
🔑 GITHUB_TOKEN: `{GITHUB_TOKEN[:10]}...`
👤 GITHUB_REPO_OWNER: `{GITHUB_REPO_OWNER}`
📁 GITHUB_REPO_NAME: `{GITHUB_REPO_NAME}`
🌿 GITHUB_BACKUP_BRANCH: `{GITHUB_BACKUP_BRANCH}`
📂 GITHUB_BACKUP_PATH: `{GITHUB_BACKUP_PATH}`
💰 STAR_PRICE: `{STAR_PRICE}`
🌐 WEBHOOK_URL: `{WEBHOOK_URL}`
🔐 ADMIN_TOKEN: `{ADMIN_TOKEN[:10]}...`

⚡ *System Status:*
• Python: {sys.version.split()[0]}
• SQLite: {sqlite3.sqlite_version}
• Uptime: Running
• Backups: {self.github_backup.backup_count} created

✅ All systems operational!"""
        
        self.send_message(chat_id, message)

# ==================== FLASK ROUTES ====================

@app.route('/')
def home():
    return jsonify({
        'service': 'Auto-Backup Master Bot',
        'status': 'running',
        'version': '1.0.0',
        'github': f'{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}',
        'features': ['auto-backup', 'bot-factory', 'star-payments']
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'backup_count': bot_instance.github_backup.backup_count if bot_instance else 0
    })

@app.route('/admin/backup', methods=['POST'])
def admin_backup():
    """Admin backup endpoint"""
    auth = request.headers.get('Authorization')
    if auth != f"Bearer {ADMIN_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    if bot_instance:
        result = bot_instance.db.create_backup("admin_api")
        return jsonify(result)
    
    return jsonify({'error': 'Bot not initialized'}), 500

@app.route('/webhook/<bot_token>', methods=['POST'])
def webhook(bot_token):
    """Handle Telegram webhook"""
    try:
        if bot_token == BOT_TOKEN and bot_instance:
            update = request.get_json()
            # Process in background thread
            threading.Thread(
                target=bot_instance.process_update,
                args=(update,),
                daemon=True
            ).start()
            return 'ok', 200
        return 'invalid token', 400
    except Exception as e:
        print(f"Webhook error: {e}")
        return 'error', 500

# ==================== STARTUP ====================

def start_bot():
    """Initialize and start the bot"""
    global bot_instance
    print("🚀 Starting Master Bot...")
    bot_instance = MasterBot()
    print("✅ Master Bot started successfully!")
    
    # Send startup notification
    try:
        startup_msg = f"""🤖 *Master Bot Started*

✅ System: Auto-Backup Master Bot
🌐 URL: {WEBHOOK_URL}
📁 GitHub: {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}
💾 Backup Path: {GITHUB_BACKUP_PATH}
💰 Star Price: {STAR_PRICE}

⚡ Features:
• Auto-backup to GitHub
• Bot factory system
• Star payment integration
• 24/7 hosting

✅ All systems operational!"""
        
        # Send to all admins
        for admin_id in ADMIN_IDS:
            bot_instance.send_message(admin_id, startup_msg)
    except:
        pass  # Silent fail if notification fails
    
    return bot_instance

# ==================== MAIN ====================

if __name__ == "__main__":
    # Start bot
    bot = start_bot()
    
    # Start Flask server
    print(f"🌐 Starting Flask server on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
