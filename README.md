# 🤖 Auto-Backup Master Bot for Telegram

A fully automated Telegram bot factory system that automatically backs up all data to GitHub and recovers on startup. Perfect for hosting other bots with zero data loss guarantee.

## 🚀 Features

### 🔄 **Auto-Recovery System**
- Automatically recovers database from GitHub on every startup
- Fallback to fresh database if recovery fails
- Sends recovery status notification to admin

### 💾 **Auto-Backup System**
- Backs up after every significant user action
- Periodic backups every 10 minutes
- Process-based triggers (after 5 database writes)
- Manual backup commands

### 📊 **Complete Management**
- User management with star balance system
- Bot creation and hosting
- Payment processing with Telegram Stars
- Web configuration interface

### 🔒 **Data Safety**
- All data stored on GitHub
- Multiple backup versions maintained
- Database integrity verification
- Transaction logging

## 🛠️ Setup

### **1. Prerequisites**
- Python 3.8+
- GitHub account
- Telegram Bot Token from [@BotFather](https://t.me/BotFather)
- Render/Railway/Heroku account (for hosting)

### **2. Environment Variables**

Create a `.env` file or set in your hosting platform:

```env
# REQUIRED
BOT_TOKEN=your_telegram_bot_token_from_botfather
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_REPO_OWNER=your_github_username
GITHUB_REPO_NAME=your_backup_repository_name
GITHUB_BACKUP_BRANCH=main
GITHUB_BACKUP_PATH=backups/masterbot

# OPTIONAL (with defaults)
PORT=8080
ADMIN_TOKEN=generate_random_token_here
STAR_PRICE=200
