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
from flask import Flask, jsonify, request, render_template_string
from threading import Thread, Lock
import traceback
import uuid
import re
import subprocess
import tempfile
import shutil
import hmac
import pickle
import zipfile
import io

print("🤖 AUTO-BACKUP MASTER BOT WITH GITHUB SYNC")
print("Auto-recover from GitHub | Auto-save on every process")
print("=" * 60)

# ==================== ENVIRONMENT CONFIGURATION ====================

class EnvConfig:
    """Load and validate environment variables for Render"""
    
    @staticmethod
    def load():
        """Load environment variables from Render"""
        config = {}
        
        # Required variables (from your Render config)
        config['BOT_TOKEN'] = os.environ.get('BOT_TOKEN')
        config['GITHUB_TOKEN'] = os.environ.get('GITHUB_TOKEN')
        config['GITHUB_REPO_OWNER'] = os.environ.get('GITHUB_REPO_OWNER')
        config['GITHUB_REPO_NAME'] = os.environ.get('GITHUB_REPO_NAME')
        config['GITHUB_BACKUP_BRANCH'] = os.environ.get('GITHUB_BACKUP_BRANCH', 'main')
        config['GITHUB_BACKUP_PATH'] = os.environ.get('GITHUB_BACKUP_PATH', 'backups/masterbot/masterbot.db')
        
        # Optional variables
        config['PORT'] = int(os.environ.get('PORT', 8080))
        config['ADMIN_TOKEN'] = os.environ.get('ADMIN_TOKEN', secrets.token_hex(32))
        config['STAR_PRICE'] = int(os.environ.get('STAR_PRICE', 200))
        
        # Auto-detect webhook URL
        render_url = os.environ.get('RENDER_EXTERNAL_URL')
        if render_url:
            config['WEBHOOK_URL'] = render_url
            config['MASTER_DOMAIN'] = render_url
        else:
            config['WEBHOOK_URL'] = f"http://localhost:{config['PORT']}"
            config['MASTER_DOMAIN'] = f"http://localhost:{config['PORT']}"
        
        # Validate required variables
        required_vars = ['BOT_TOKEN', 'GITHUB_TOKEN', 'GITHUB_REPO_OWNER', 'GITHUB_REPO_NAME']
        for var in required_vars:
            if not config[var]:
                print(f"❌ ERROR: {var} environment variable is required!")
                sys.exit(1)
        
        print("✅ Environment Variables Loaded:")
        print(f"   🤖 BOT_TOKEN: {config['BOT_TOKEN'][:15]}...")
        print(f"   📁 GitHub Repo: {config['GITHUB_REPO_OWNER']}/{config['GITHUB_REPO_NAME']}")
        print(f"   🌿 Branch: {config['GITHUB_BACKUP_BRANCH']}")
        print(f"   💾 Backup Path: {config['GITHUB_BACKUP_PATH']}")
        print(f"   🌐 Webhook URL: {config['WEBHOOK_URL']}")
        
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

# Flask App
app = Flask(__name__)
bot_factory = None

# ==================== GITHUB AUTO-BACKUP MANAGER ====================

class GitHubAutoBackup:
    """Automatic GitHub backup with recovery system"""
    
    def __init__(self, token, repo_owner, repo_name, branch='main', backup_path='backups/masterbot'):
        self.token = token
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.branch = branch
        self.backup_path = backup_path
        self.api_base = "https://api.github.com"
        self.repo_full = f"{repo_owner}/{repo_name}"
        self.auth_header = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Local backup state
        self.local_db_path = "masterbot.db"
        self.backup_lock = Lock()
        self.last_backup_time = None
        self.backup_count = 0
        
        # Ensure local backup directory exists
        os.makedirs(os.path.dirname(self.local_db_path), exist_ok=True)
        
        print(f"✅ GitHub Auto-Backup initialized")
        print(f"   📁 Repository: {self.repo_full}")
        print(f"   🌿 Branch: {self.branch}")
        print(f"   💾 Backup Path: {self.backup_path}")
    
    def recover_from_backup(self):
        """Recover database from latest GitHub backup on startup"""
        try:
            print("🔄 Attempting to recover from GitHub backup...")
            
            # Get latest backup from GitHub
            latest_backup = self.get_latest_backup()
            
            if latest_backup:
                print(f"✅ Found backup: {latest_backup['sha'][:8]} - {latest_backup['message']}")
                
                # Download and restore backup
                restored = self.restore_backup(latest_backup['sha'])
                
                if restored:
                    print("✅ Successfully recovered database from GitHub")
                    return True
                else:
                    print("⚠️  Could not restore backup, using fresh database")
            else:
                print("⚠️  No backup found, starting with fresh database")
            
            # Create fresh database if no backup or restore failed
            self.create_fresh_database()
            return False
            
        except Exception as e:
            print(f"❌ Recovery error: {e}")
            traceback.print_exc()
            self.create_fresh_database()
            return False
    
    def get_latest_backup(self):
        """Get latest backup commit from GitHub"""
        try:
            # Get commits from the backup file
            url = f"{self.api_base}/repos/{self.repo_full}/commits"
            params = {
                'path': self.backup_path,
                'sha': self.branch,
                'per_page': 1
            }
            
            response = requests.get(url, headers=self.auth_header, params=params, timeout=30)
            
            if response.status_code == 200:
                commits = response.json()
                if commits:
                    latest = commits[0]
                    return {
                        'sha': latest['sha'],
                        'message': latest['commit']['message'],
                        'date': latest['commit']['committer']['date'],
                        'author': latest['commit']['committer']['name']
                    }
            
            return None
            
        except Exception as e:
            print(f"❌ Error getting latest backup: {e}")
            return None
    
    def restore_backup(self, commit_sha):
        """Restore database from specific commit"""
        try:
            # Get file content from commit
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{self.backup_path}"
            params = {'ref': commit_sha}
            
            response = requests.get(url, headers=self.auth_header, params=params, timeout=30)
            
            if response.status_code == 200:
                file_data = response.json()
                
                if 'content' in file_data:
                    # Decode base64 content
                    content = base64.b64decode(file_data['content']).decode('utf-8')
                    
                    # Check if it's JSON (backup metadata) or SQLite
                    if content.startswith('SQLite format 3'):
                        # It's a SQLite database
                        with open(self.local_db_path, 'wb') as f:
                            f.write(base64.b64decode(file_data['content']))
                        
                        # Verify the restored database
                        if self.verify_database():
                            print(f"✅ Database restored from commit {commit_sha[:8]}")
                            return True
                    else:
                        # Try to parse as JSON backup
                        backup_data = json.loads(content)
                        return self.restore_from_json_backup(backup_data)
            
            return False
            
        except Exception as e:
            print(f"❌ Restore error: {e}")
            return False
    
    def restore_from_json_backup(self, backup_data):
        """Restore from JSON backup format"""
        try:
            # Create new database
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            # Restore tables
            for table_name, table_data in backup_data.get('tables', {}).items():
                # Create table
                cursor.execute(table_data['schema'])
                
                # Insert data
                for row in table_data['rows']:
                    placeholders = ', '.join(['?'] * len(row))
                    cursor.execute(f"INSERT INTO {table_name} VALUES ({placeholders})", row)
            
            conn.commit()
            conn.close()
            
            print(f"✅ Restored {len(backup_data.get('tables', {}))} tables from JSON backup")
            return True
            
        except Exception as e:
            print(f"❌ JSON restore error: {e}")
            return False
    
    def create_fresh_database(self):
        """Create fresh database with all required tables"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            # Create all required tables
            cursor.executescript('''
                -- Users table
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    stars_balance INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Star payments table
                CREATE TABLE IF NOT EXISTS star_payments (
                    payment_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    stars_amount INTEGER,
                    payment_method TEXT,
                    transaction_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    verified_at TIMESTAMP,
                    verified_by INTEGER
                );
                
                -- Bots table (user-created bots)
                CREATE TABLE IF NOT EXISTS user_bots (
                    bot_token TEXT PRIMARY KEY,
                    bot_username TEXT,
                    owner_id INTEGER,
                    template_used TEXT,
                    stars_paid INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    backup_id TEXT
                );
                
                -- Bot backups table
                CREATE TABLE IF NOT EXISTS bot_backups (
                    backup_id TEXT PRIMARY KEY,
                    bot_token TEXT,
                    backup_type TEXT,
                    backup_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_hash TEXT
                );
                
                -- Process logs table (for auto-backup triggers)
                CREATE TABLE IF NOT EXISTS process_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    process_type TEXT,
                    process_data TEXT,
                    user_id INTEGER,
                    affected_rows INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    backed_up INTEGER DEFAULT 0
                );
                
                -- System settings table
                CREATE TABLE IF NOT EXISTS system_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                -- Insert default settings
                INSERT OR IGNORE INTO system_settings (setting_key, setting_value) VALUES
                    ('star_price', '200'),
                    ('auto_backup_enabled', '1'),
                    ('backup_interval', '5'),
                    ('last_full_backup', datetime('now')),
                    ('total_backups', '0');
            ''')
            
            conn.commit()
            conn.close()
            
            print("✅ Fresh database created with all tables")
            
            # Create initial backup
            self.create_backup("initial_backup")
            
            return True
            
        except Exception as e:
            print(f"❌ Error creating fresh database: {e}")
            return False
    
    def verify_database(self):
        """Verify database integrity"""
        try:
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            # Check if required tables exist
            required_tables = ['users', 'star_payments', 'user_bots', 'bot_backups', 'process_logs', 'system_settings']
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            existing_tables = [row[0] for row in cursor.fetchall()]
            
            missing_tables = [t for t in required_tables if t not in existing_tables]
            
            conn.close()
            
            if missing_tables:
                print(f"⚠️  Missing tables: {missing_tables}")
                return False
            
            print(f"✅ Database verified: {len(existing_tables)} tables found")
            return True
            
        except:
            return False
    
    def create_backup(self, reason="auto_backup"):
        """Create backup and push to GitHub"""
        with self.backup_lock:
            try:
                print(f"💾 Creating backup: {reason}")
                
                # Read database file
                with open(self.local_db_path, 'rb') as f:
                    db_content = f.read()
                
                # Create backup with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = f"masterbot_backup_{timestamp}.db"
                backup_path_full = f"{self.backup_path}/{backup_filename}"
                
                # Encode content
                encoded_content = base64.b64encode(db_content).decode('utf-8')
                
                # Check if file already exists
                check_url = f"{self.api_base}/repos/{self.repo_full}/contents/{backup_path_full}"
                response = requests.get(check_url, headers=self.auth_header, timeout=30)
                
                if response.status_code == 200:
                    # File exists, get its SHA
                    existing_file = response.json()
                    sha = existing_file['sha']
                else:
                    sha = None
                
                # Prepare commit
                commit_data = {
                    "message": f"🤖 Auto-backup: {reason} - {timestamp}",
                    "content": encoded_content,
                    "branch": self.branch
                }
                
                if sha:
                    commit_data["sha"] = sha
                
                # Create or update file
                url = f"{self.api_base}/repos/{self.repo_full}/contents/{backup_path_full}"
                response = requests.put(url, headers=self.auth_header, json=commit_data, timeout=30)
                
                if response.status_code in [200, 201]:
                    result = response.json()
                    
                    # Update latest pointer
                    self.update_latest_pointer(backup_filename, result['commit']['sha'])
                    
                    # Update backup stats
                    self.backup_count += 1
                    self.last_backup_time = datetime.now()
                    
                    print(f"✅ Backup created: {backup_filename}")
                    print(f"   📝 Commit: {result['commit']['sha'][:8]}")
                    print(f"   📊 Total backups: {self.backup_count}")
                    
                    return {
                        'success': True,
                        'filename': backup_filename,
                        'commit_sha': result['commit']['sha'],
                        'size': len(db_content)
                    }
                else:
                    print(f"❌ Backup failed: {response.status_code} - {response.text}")
                    return {'success': False, 'error': response.text}
                    
            except Exception as e:
                print(f"❌ Backup error: {e}")
                return {'success': False, 'error': str(e)}
    
    def update_latest_pointer(self, filename, commit_sha):
        """Update latest.txt pointer to newest backup"""
        try:
            pointer_content = f"{filename}|{commit_sha}|{datetime.now().isoformat()}"
            encoded_content = base64.b64encode(pointer_content.encode('utf-8')).decode('utf-8')
            
            pointer_path = f"{self.backup_path}/latest.txt"
            
            # Check if pointer exists
            check_url = f"{self.api_base}/repos/{self.repo_full}/contents/{pointer_path}"
            response = requests.get(check_url, headers=self.auth_header, timeout=30)
            
            sha = None
            if response.status_code == 200:
                sha = response.json()['sha']
            
            # Update pointer
            commit_data = {
                "message": f"📌 Update latest pointer to {filename}",
                "content": encoded_content,
                "branch": self.branch
            }
            
            if sha:
                commit_data["sha"] = sha
            
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{pointer_path}"
            response = requests.put(url, headers=self.auth_header, json=commit_data, timeout=30)
            
            if response.status_code in [200, 201]:
                print(f"📌 Latest pointer updated to: {filename}")
                return True
            else:
                print(f"⚠️  Failed to update pointer: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"⚠️  Pointer update error: {e}")
            return False
    
    def auto_backup_trigger(self, process_type, process_data=None, user_id=None, affected_rows=0):
        """Trigger auto-backup based on process type"""
        try:
            # Get backup settings
            conn = sqlite3.connect(self.local_db_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'auto_backup_enabled'")
            auto_backup_enabled = cursor.fetchone()
            
            if not auto_backup_enabled or auto_backup_enabled[0] != '1':
                conn.close()
                return False
            
            # Log the process
            log_data = json.dumps({
                'type': process_type,
                'data': process_data,
                'user_id': user_id,
                'timestamp': datetime.now().isoformat()
            })
            
            cursor.execute('''
                INSERT INTO process_logs (process_type, process_data, user_id, affected_rows)
                VALUES (?, ?, ?, ?)
            ''', (process_type, log_data, user_id, affected_rows))
            
            log_id = cursor.lastrowid
            
            # Check if backup is needed
            cursor.execute('''
                SELECT COUNT(*) FROM process_logs 
                WHERE backed_up = 0 AND created_at > datetime('now', '-1 minute')
            ''')
            pending_logs = cursor.fetchone()[0]
            
            cursor.execute("SELECT setting_value FROM system_settings WHERE setting_key = 'backup_interval'")
            backup_interval = int(cursor.fetchone()[0] if cursor.fetchone() else 5)
            
            conn.commit()
            conn.close()
            
            # Trigger backup if conditions met
            if pending_logs >= backup_interval or process_type in ['star_payment', 'bot_creation', 'user_registration']:
                reason = f"auto_after_{process_type}_{log_id}"
                self.create_backup(reason)
                
                # Mark logs as backed up
                conn = sqlite3.connect(self.local_db_path)
                cursor = conn.cursor()
                cursor.execute('UPDATE process_logs SET backed_up = 1 WHERE log_id <= ?', (log_id,))
                conn.commit()
                conn.close()
                
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Auto-backup trigger error: {e}")
            return False
    
    def get_backup_stats(self):
        """Get backup statistics"""
        try:
            url = f"{self.api_base}/repos/{self.repo_full}/contents/{self.backup_path}"
            response = requests.get(url, headers=self.auth_header, timeout=30)
            
            if response.status_code == 200:
                files = response.json()
                backup_files = [f for f in files if f['name'].endswith('.db')]
                
                return {
                    'total_backups': len(backup_files),
                    'latest_backup': backup_files[0]['name'] if backup_files else None,
                    'total_size': sum(f['size'] for f in backup_files),
                    'last_backup_time': self.last_backup_time.isoformat() if self.last_backup_time else None,
                    'backup_count': self.backup_count
                }
            else:
                return {'error': 'Could not fetch backup stats'}
                
        except Exception as e:
            return {'error': str(e)}

# ==================== AUTO-BACKUP DATABASE WRAPPER ====================

class AutoBackupDatabase:
    """Database wrapper that auto-backups after every write operation"""
    
    def __init__(self, db_path, github_backup):
        self.db_path = db_path
        self.github_backup = github_backup
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # Enable Write-Ahead Logging
        self.setup_callbacks()
        
        print("✅ Auto-backup database initialized")
    
    def setup_callbacks(self):
        """Setup commit callbacks for auto-backup"""
        def commit_callback():
            # This gets called after every commit
            # We'll handle backups in individual methods instead
            pass
        
        self.conn.set_commit_hook(commit_callback)
    
    def execute_with_backup(self, query, params=(), process_type=None, user_id=None):
        """Execute query with auto-backup trigger"""
        try:
            cursor = self.conn.cursor()
            
            # Execute the query
            if isinstance(query, str):
                cursor.execute(query, params)
            else:
                # Multiple queries
                cursor.executescript(query)
            
            affected_rows = cursor.rowcount
            
            # Commit transaction
            self.conn.commit()
            
            # Trigger auto-backup if this was a write operation
            if process_type and self.is_write_query(query):
                backup_data = {
                    'query': query[:100] + '...' if len(query) > 100 else query,
                    'params': str(params)[:200],
                    'affected_rows': affected_rows
                }
                
                self.github_backup.auto_backup_trigger(
                    process_type=process_type,
                    process_data=backup_data,
                    user_id=user_id,
                    affected_rows=affected_rows
                )
            
            return cursor
            
        except Exception as e:
            self.conn.rollback()
            raise e
    
    def is_write_query(self, query):
        """Check if query modifies data"""
        write_keywords = ['INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP', 'ALTER']
        query_upper = query.upper().strip()
        return any(keyword in query_upper for keyword in write_keywords)
    
    def backup_now(self, reason="manual_backup"):
        """Trigger immediate backup"""
        return self.github_backup.create_backup(reason)
    
    def get_connection(self):
        """Get raw connection (use with caution)"""
        return self.conn

# ==================== MASTER BOT WITH AUTO-BACKUP ====================

class AutoBackupMasterBot:
    """Master bot that auto-backups to GitHub on every process"""
    
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/"
        
        # Initialize GitHub auto-backup
        self.github_backup = GitHubAutoBackup(
            token=GITHUB_TOKEN,
            repo_owner=GITHUB_REPO_OWNER,
            repo_name=GITHUB_REPO_NAME,
            branch=GITHUB_BACKUP_BRANCH,
            backup_path=os.path.dirname(GITHUB_BACKUP_PATH)
        )
        
        # Recover from backup on startup
        recovered = self.github_backup.recover_from_backup()
        
        # Initialize auto-backup database
        self.db = AutoBackupDatabase("masterbot.db", self.github_backup)
        
        # Setup webhook
        self.setup_webhook()
        
        # Start periodic backup thread
        self.start_periodic_backup()
        
        # Send startup notification
        self.send_startup_notification(recovered)
    
    def setup_webhook(self):
        """Setup master bot webhook"""
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
                print(f"⚠️  Webhook setup failed: {response.json()}")
                
        except Exception as e:
            print(f"⚠️  Webhook error: {e}")
    
    def send_startup_notification(self, recovered):
        """Send startup notification with recovery status"""
        try:
            # Get backup stats
            stats = self.github_backup.get_backup_stats()
            
            # Send to admin
            admin_id = 7713987088  # Your admin ID
            
            if recovered:
                message = f"""✅ *Master Bot Started with Recovery*

🤖 *System Status:*
• Database recovered from GitHub backup
• Auto-backup system: ACTIVE
• Webhook: {WEBHOOK_URL}
• GitHub: {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}

📊 *Backup Stats:*
• Total backups: {stats.get('total_backups', 0)}
• Latest: {stats.get('latest_backup', 'N/A')}
• Auto-backup count: {self.github_backup.backup_count}

⚡ *Features:*
• Auto-backup on every process
• GitHub recovery on startup
• Periodic backups every 10 min
• Manual backup commands

🚀 System ready!"""
            else:
                message = f"""🔄 *Master Bot Started Fresh*

🤖 *System Status:*
• Fresh database created
• Auto-backup system: ACTIVE
• Webhook: {WEBHOOK_URL}
• GitHub: {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}

⚠️ *Note:* No backup found or recovery failed

⚡ *Features:*
• Auto-backup on every process
• GitHub recovery on startup
• Periodic backups every 10 min
• Manual backup commands

🚀 System ready!"""
            
            requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    'chat_id': admin_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }
            )
            
        except Exception as e:
            print(f"⚠️  Startup notification failed: {e}")
    
    def start_periodic_backup(self):
        """Start periodic backup thread"""
        def periodic_backup():
            while True:
                try:
                    time.sleep(600)  # 10 minutes
                    
                    # Check if periodic backup is needed
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM process_logs WHERE backed_up = 0")
                    pending = cursor.fetchone()[0]
                    
                    if pending > 0:
                        print(f"⏰ Periodic backup triggered ({pending} pending logs)")
                        self.db.backup_now("periodic_backup")
                        
                except Exception as e:
                    print(f"⚠️  Periodic backup error: {e}")
        
        thread = Thread(target=periodic_backup, daemon=True)
        thread.start()
        print("✅ Periodic backup thread started (every 10 minutes)")
    
    def process_update(self, update):
        """Process update with auto-backup"""
        try:
            if 'message' in update:
                msg = update['message']
                chat_id = msg['chat']['id']
                user_id = msg['from']['id']
                user_name = msg['from'].get('first_name', 'User')
                
                if 'text' in msg:
                    text = msg['text']
                    
                    # Register/update user (triggers backup)
                    self.register_user(user_id, user_name)
                    
                    if text == '/start':
                        self.handle_start(chat_id, user_id, user_name)
                    
                    elif text == '/backup':
                        self.handle_backup(chat_id, user_id)
                    
                    elif text == '/stats':
                        self.handle_stats(chat_id)
                    
                    elif text == '/mystats':
                        self.handle_user_stats(chat_id, user_id)
                    
                    elif text.startswith('/addstars'):
                        self.handle_add_stars(chat_id, user_id, text)
                    
                    elif text.startswith('/createbot'):
                        self.handle_create_bot(chat_id, user_id, user_name, text)
                    
                    elif text == '/restore':
                        self.handle_restore(chat_id, user_id)
                    
                    elif text == '/help':
                        self.handle_help(chat_id)
        
        except Exception as e:
            print(f"❌ Process error: {e}")
            traceback.print_exc()
    
    def register_user(self, user_id, user_name):
        """Register or update user (triggers auto-backup)"""
        try:
            cursor = self.db.execute_with_backup(
                '''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_seen)
                VALUES (?, ?, ?, datetime('now'))
                ''',
                (user_id, user_name, user_name),
                process_type='user_update',
                user_id=user_id
            )
            
            print(f"📝 User registered/updated: {user_id} - {user_name}")
            return True
            
        except Exception as e:
            print(f"❌ User registration error: {e}")
            return False
    
    def handle_start(self, chat_id, user_id, user_name):
        """Handle /start command"""
        # Get backup stats
        stats = self.github_backup.get_backup_stats()
        
        message = f"""🤖 *Auto-Backup Master Bot*

Hello {user_name}! I'm a master bot that *auto-saves everything to GitHub*.

⚡ *Key Features:*
• 🔄 **Auto-recover** from GitHub on startup
• 💾 **Auto-backup** after every action
• 📊 **Full history** of all processes
• 🔒 **Data safety** with GitHub backups

📁 *GitHub Backup:*
• Repository: `{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}`
• Branch: `{GITHUB_BACKUP_BRANCH}`
• Path: `{GITHUB_BACKUP_PATH}`
• Backups: {stats.get('total_backups', 0)} files

🔄 *Auto-Backup Triggers:*
• User registration/updates
• Star payments
• Bot creation
• Every 5 actions
• Every 10 minutes

📋 *Commands:*
/backup - Create manual backup
/stats - System statistics
/mystats - Your statistics
/addstars AMOUNT - Add stars (admin)
/createbot TOKEN - Create bot
/restore - Restore from backup
/help - Detailed help

💡 *Your data is automatically backed up after every action!*"""
        
        self.send_message(chat_id, message)
    
    def handle_backup(self, chat_id, user_id):
        """Handle /backup command"""
        message = "💾 Creating manual backup..."
        self.send_message(chat_id, message)
        
        result = self.db.backup_now(f"manual_by_user_{user_id}")
        
        if result.get('success'):
            stats = self.github_backup.get_backup_stats()
            
            success_msg = f"""✅ *Backup Created Successfully!*

📁 *Backup Details:*
• File: `{result['filename']}`
• Size: {result['size']:,} bytes
• Commit: `{result['commit_sha'][:8]}`
• Time: {datetime.now().strftime('%H:%M:%S')}

📊 *Backup Statistics:*
• Total backups: {stats.get('total_backups', 0)}
• Auto-backup count: {self.github_backup.backup_count}
• Last backup: {self.github_backup.last_backup_time.strftime('%Y-%m-%d %H:%M') if self.github_backup.last_backup_time else 'Never'}

✅ Your data is safely stored on GitHub!"""
            
            self.send_message(chat_id, success_msg)
        else:
            error_msg = f"""❌ *Backup Failed*

Error: {result.get('error', 'Unknown error')}

Please try again or contact admin."""
            
            self.send_message(chat_id, error_msg)
    
    def handle_stats(self, chat_id):
        """Handle /stats command"""
        # Get database stats
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM star_payments WHERE status = 'verified'")
        payment_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_bots WHERE is_active = 1")
        bot_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM process_logs")
        process_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM process_logs WHERE backed_up = 0")
        pending_backup = cursor.fetchone()[0]
        
        # Get backup stats
        backup_stats = self.github_backup.get_backup_stats()
        
        message = f"""📊 *System Statistics*

👥 *Users:*
• Total users: {user_count}
• Verified payments: {payment_count}
• Active bots: {bot_count}

💾 *Backup System:*
• Total backups: {backup_stats.get('total_backups', 0)}
• Auto-backup count: {self.github_backup.backup_count}
• Pending processes: {pending_backup}
• Total processes: {process_count}

📁 *GitHub:*
• Repository: {GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}
• Branch: {GITHUB_BACKUP_BRANCH}
• Latest: {backup_stats.get('latest_backup', 'N/A')}

⚙️ *System:*
• Webhook: {WEBHOOK_URL}
• Last backup: {self.github_backup.last_backup_time.strftime('%H:%M:%S') if self.github_backup.last_backup_time else 'Never'}
• Uptime: {self.get_uptime()}

✅ *Auto-backup is ACTIVE*"""
        
        self.send_message(chat_id, message)
    
    def handle_user_stats(self, chat_id, user_id):
        """Handle /mystats command"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT username, stars_balance, created_at, last_seen 
            FROM users WHERE user_id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        
        if user:
            username, stars, created, last_seen = user
            
            cursor.execute("SELECT COUNT(*) FROM user_bots WHERE owner_id = ? AND is_active = 1", (user_id,))
            bot_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(stars_amount) FROM star_payments WHERE user_id = ? AND status = 'verified'", (user_id,))
            total_stars = cursor.fetchone()[0] or 0
            
            message = f"""📊 *Your Statistics*

👤 *Profile:*
• Username: {username}
• User ID: `{user_id}`
• Joined: {created[:10]}
• Last seen: {last_seen[:16]}

💰 *Stars:*
• Balance: {stars} stars
• Total earned: {total_stars} stars
• Active bots: {bot_count}

📁 *Backup Status:*
• Your data is auto-backed up
• GitHub: {GITHUB_REPO_NAME}
• All actions are logged

🔄 *Recent activity is automatically saved to GitHub!*"""
            
            self.send_message(chat_id, message)
        else:
            self.send_message(chat_id, "❌ User not found. Send /start to register.")
    
    def handle_add_stars(self, chat_id, user_id, text):
        """Handle /addstars command (admin only)"""
        # Check if admin
        if user_id not in [7713987088, 7475473197]:  # Your admin IDs
            self.send_message(chat_id, "❌ Admin access required.")
            return
        
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, "Usage: /addstars AMOUNT [USER_ID]")
            return
        
        try:
            amount = int(parts[1])
            target_user = int(parts[2]) if len(parts) > 2 else user_id
            
            # Add stars
            cursor = self.db.execute_with_backup(
                '''
                UPDATE users 
                SET stars_balance = stars_balance + ? 
                WHERE user_id = ?
                ''',
                (amount, target_user),
                process_type='add_stars',
                user_id=user_id
            )
            
            if cursor.rowcount > 0:
                # Record payment
                payment_id = f"admin_add_{secrets.token_hex(8)}"
                cursor = self.db.execute_with_backup(
                    '''
                    INSERT INTO star_payments (payment_id, user_id, stars_amount, payment_method, status, verified_at)
                    VALUES (?, ?, ?, 'admin_add', 'verified', datetime('now'))
                    ''',
                    (payment_id, target_user, amount),
                    process_type='star_payment',
                    user_id=user_id
                )
                
                self.send_message(chat_id, f"✅ Added {amount} stars to user {target_user}")
            else:
                self.send_message(chat_id, "❌ User not found")
                
        except ValueError:
            self.send_message(chat_id, "❌ Invalid amount. Use numbers only.")
    
    def handle_create_bot(self, chat_id, user_id, user_name, text):
        """Handle /createbot command"""
        parts = text.split()
        if len(parts) < 2:
            self.send_message(chat_id, 
                "Usage: /createbot BOT_TOKEN\n\n"
                "Get token from @BotFather")
            return
        
        bot_token = parts[1]
        
        # Test bot token
        test_url = f"https://api.telegram.org/bot{bot_token}/getMe"
        try:
            response = requests.get(test_url, timeout=10)
            if not response.json().get('ok'):
                self.send_message(chat_id, "❌ Invalid bot token")
                return
            
            bot_info = response.json()['result']
            bot_username = bot_info['username']
            
        except:
            self.send_message(chat_id, "❌ Could not verify bot token")
            return
        
        # Check user balance
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT stars_balance FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            self.send_message(chat_id, "❌ User not registered. Send /start first.")
            return
        
        stars_balance = user[0]
        bot_price = 100  # Stars required to create a bot
        
        if stars_balance < bot_price:
            self.send_message(chat_id,
                f"❌ Insufficient stars\n\n"
                f"Required: {bot_price} stars\n"
                f"Your balance: {stars_balance} stars\n\n"
                f"Ask admin for stars: /addstars")
            return
        
        # Create bot record
        backup_id = f"bot_{secrets.token_hex(8)}"
        cursor = self.db.execute_with_backup(
            '''
            INSERT INTO user_bots (bot_token, bot_username, owner_id, stars_paid, backup_id)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (bot_token[:50], bot_username, user_id, bot_price, backup_id),
            process_type='bot_creation',
            user_id=user_id
        )
        
        # Deduct stars
        cursor = self.db.execute_with_backup(
            'UPDATE users SET stars_balance = stars_balance - ? WHERE user_id = ?',
            (bot_price, user_id),
            process_type='star_deduction',
            user_id=user_id
        )
        
        # Set webhook for the new bot
        webhook_url = f"{WEBHOOK_URL}/webhook/{bot_token}"
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={'url': webhook_url}
        )
        
        # Create bot backup
        bot_data = {
            'bot_token': bot_token[:8] + "...",
            'bot_username': bot_username,
            'owner_id': user_id,
            'owner_name': user_name,
            'created_at': datetime.now().isoformat(),
            'price_paid': bot_price
        }
        
        self.github_backup.backup_bot_config(bot_token, bot_data)
        
        success_msg = f"""✅ *Bot Created Successfully!*

🤖 Bot: @{bot_username}
👤 Owner: {user_name}
💰 Price: {bot_price} stars
📉 New balance: {stars_balance - bot_price} stars

🔗 *Webhook:* {webhook_url}

📁 *Auto-Backup Enabled:*
• Bot configuration saved to GitHub
• All future actions auto-backed up
• Backup ID: `{backup_id}`

⚙️ *Features:*
• Auto-backup system included
• Star payment system
• User management
• Web configuration

🚀 Your bot is ready: @{bot_username}"""
        
        self.send_message(chat_id, success_msg)
    
    def handle_restore(self, chat_id, user_id):
        """Handle /restore command"""
        # Check if admin
        if user_id not in [7713987088, 7475473197]:
            self.send_message(chat_id, "❌ Admin access required for restore.")
            return
        
        message = """🔄 *Restore from Backup*

Choose restore option:

1️⃣ *Latest Backup* - Restore from most recent backup
2️⃣ *Specific Backup* - Restore from specific commit
3️⃣ *List Backups* - Show available backups

Reply with number or use:
/restore latest
/restore list
/restore COMMIT_SHA"""
        
        self.send_message(chat_id, message)
    
    def handle_help(self, chat_id):
        """Handle /help command"""
        message = f"""🆘 *Auto-Backup Master Bot Help*

🤖 *What I Do:*
I automatically backup EVERY process to GitHub:
• User registrations
• Star payments
• Bot creations
• Settings changes
• All database writes

⚡ *Auto-Backup Features:*
1. **Recovery on Startup** - Auto-restore from GitHub
2. **Process-based Backup** - Backup after every action
3. **Periodic Backup** - Every 10 minutes
4. **Manual Backup** - On-demand backups
5. **GitHub Storage** - All data on GitHub

📁 *GitHub Configuration:*
• Repository: `{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}`
• Branch: `{GITHUB_BACKUP_BRANCH}`
• Path: `{GITHUB_BACKUP_PATH}`
• Token: `{GITHUB_TOKEN[:10]}...`

🔧 *Available Commands:*
/start - Welcome message
/backup - Create manual backup
/stats - System statistics
/mystats - Your statistics
/addstars AMOUNT - Add stars (admin)
/createbot TOKEN - Create bot
/restore - Restore from backup (admin)
/help - This message

💡 *Data Safety:*
All your data is automatically backed up to GitHub after every action. No manual saving needed!

⚙️ *Admin Commands:*
/addstars, /restore, database management

❓ *Need Help?* Contact the bot owner."""
        
        self.send_message(chat_id, message)
    
    def get_uptime(self):
        """Get bot uptime"""
        # This would track actual uptime
        return "Running"
    
    def send_message(self, chat_id, text):
        """Send Telegram message"""
        try:
            requests.post(f"{self.base_url}sendMessage", json={
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True
            })
        except Exception as e:
            print(f"❌ Send message error: {e}")

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    return jsonify({
        'service': 'Auto-Backup Master Bot',
        'status': 'running',
        'github_backup': f'{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}',
        'backup_path': GITHUB_BACKUP_PATH,
        'features': [
            'Auto-recover from GitHub on startup',
            'Auto-backup after every process',
            'Periodic backups every 10 minutes',
            'Manual backup triggers',
            'Process logging and tracking'
        ]
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'auto_backup': {
            'enabled': True,
            'last_backup': bot_factory.github_backup.last_backup_time.isoformat() if bot_factory and bot_factory.github_backup.last_backup_time else None,
            'total_backups': bot_factory.github_backup.backup_count if bot_factory else 0
        }
    })

@app.route('/admin/backup', methods=['POST'])
def admin_backup():
    """Admin trigger for manual backup"""
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {ADMIN_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    reason = data.get('reason', 'admin_triggered')
    
    if bot_factory:
        result = bot_factory.db.backup_now(reason)
        return jsonify(result)
    
    return jsonify({'error': 'Bot factory not initialized'}), 500

@app.route('/admin/restore', methods=['POST'])
def admin_restore():
    """Admin restore from backup"""
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {ADMIN_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    commit_sha = data.get('commit_sha')
    
    if bot_factory:
        if commit_sha:
            result = bot_factory.github_backup.restore_backup(commit_sha)
        else:
            # Get latest and restore
            latest = bot_factory.github_backup.get_latest_backup()
            if latest:
                result = bot_factory.github_backup.restore_backup(latest['sha'])
            else:
                result = {'success': False, 'error': 'No backups found'}
        
        return jsonify(result)
    
    return jsonify({'error': 'Bot factory not initialized'}), 500

@app.route('/admin/stats', methods=['GET'])
def admin_stats():
    """Admin statistics"""
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {ADMIN_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401
    
    if bot_factory:
        # Get database stats
        conn = bot_factory.db.get_connection()
        cursor = conn.cursor()
        
        stats = {
            'users': {},
            'payments': {},
            'bots': {},
            'backups': {},
            'processes': {}
        }
        
        # User stats
        cursor.execute("SELECT COUNT(*) FROM users")
        stats['users']['total'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen > datetime('now', '-1 day')")
        stats['users']['active_today'] = cursor.fetchone()[0]
        
        # Payment stats
        cursor.execute("SELECT COUNT(*) FROM star_payments")
        stats['payments']['total'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(stars_amount) FROM star_payments WHERE status = 'verified'")
        stats['payments']['total_stars'] = cursor.fetchone()[0] or 0
        
        # Bot stats
        cursor.execute("SELECT COUNT(*) FROM user_bots")
        stats['bots']['total'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM user_bots WHERE is_active = 1")
        stats['bots']['active'] = cursor.fetchone()[0]
        
        # Process stats
        cursor.execute("SELECT COUNT(*) FROM process_logs")
        stats['processes']['total'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM process_logs WHERE backed_up = 0")
        stats['processes']['pending_backup'] = cursor.fetchone()[0]
        
        # Backup stats
        backup_stats = bot_factory.github_backup.get_backup_stats()
        stats['backups'] = backup_stats
        
        conn.close()
        
        return jsonify(stats)
    
    return jsonify({'error': 'Bot factory not initialized'}), 500

@app.route('/webhook/<bot_token>', methods=['POST'])
def webhook_handler(bot_token):
    """Handle webhook for master bot"""
    try:
        if bot_token == BOT_TOKEN:
            update = request.get_json()
            if bot_factory:
                # Process in background thread
                threading.Thread(
                    target=bot_factory.process_update,
                    args=(update,)
                ).start()
            return 'ok', 200
        else:
            # Handle user bot webhooks
            return 'ok', 200
            
    except Exception as e:
        print(f"Webhook error: {e}")
        return 'error', 500

def start_flask():
    """Start Flask server"""
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)

# ==================== MAIN EXECUTION ====================

if __name__ == "__main__":
    print("🚀 Starting Auto-Backup Master Bot...")
    print("=" * 60)
    
    # Start Flask in background
    flask_thread = Thread(target=start_flask, daemon=True)
    flask_thread.start()
    time.sleep(2)
    
    print(f"✅ Flask server started on port {PORT}")
    print(f"🌐 Webhook URL: {WEBHOOK_URL}/webhook/{BOT_TOKEN[:15]}...")
    
    # Initialize master bot with auto-backup
    bot_factory = AutoBackupMasterBot(BOT_TOKEN)
    
    print("🤖 Auto-Backup Master Bot is running!")
    print("💾 Auto-backup features:")
    print("   • Recover from GitHub on startup")
    print("   • Auto-backup after every process")
    print("   • Periodic backups every 10 minutes")
    print("   • Manual backup triggers")
    print("   • Process logging and tracking")
    print("=" * 60)
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(3600)  # Sleep for 1 hour
    except KeyboardInterrupt:
        print("\n🛑 Auto-Backup Master Bot stopped")
        # Create final backup before exit
        if bot_factory:
            bot_factory.db.backup_now("shutdown_backup")
