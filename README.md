# 📚 Study Materials Telegram Bot

A production-ready Telegram bot for class representatives to sell printed study materials.  
Students browse materials, pay via Paystack, and receive a **unique pickup token** to collect their printed copy.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📚 Browse materials | Students see all active materials with prices |
| 💳 Paystack payment | Secure payment link generated per order |
| 🎟 Pickup token | Unique `MAT-XXXXXX` token issued after payment |
| 🔁 Duplicate prevention | Re-verifying a paid reference returns the existing token |
| 📦 SQLite database | Materials & payments stored — no coding to add new items |
| 👤 Admin commands | Add/remove materials, list payments, broadcast messages |
| 📣 Admin notifications | Instant Telegram alert for every successful payment |
| 🇳🇬 Naira formatting | All amounts displayed as ₦2,000 etc. |

---

## 🗂 Project Structure

```
bot/
├── main.py           # Entry point — starts the bot
├── database.py       # SQLite layer (materials, payments, users)
├── paystack.py       # Paystack API (initialize + verify)
├── utils.py          # Token generator, Naira formatter
├── handlers/
│   ├── user.py       # /start, browse, buy, verify
│   └── admin.py      # /addmaterial, /removematerial, /listpayments, /broadcast
├── data/
│   └── bot.db        # SQLite database (auto-created on first run)
requirements.txt      # Python dependencies
.env.example          # Template for environment variables
README.md             # This file
```

---

## ⚙️ Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. "Study Materials Bot") and a username (e.g. `studymat_bot`)
4. BotFather gives you a **token** like `8283144990:AAHkT_VlQ...` — copy it

### 2. Get Paystack API Keys

1. Go to [paystack.com](https://paystack.com) and log in
2. Navigate to **Settings → API Keys & Webhooks**
3. Copy your **Secret Key** (starts with `sk_live_` for live or `sk_test_` for test mode)
4. Copy your **Public Key** (starts with `pk_live_` or `pk_test_`) — optional for the bot

### 3. Get Your Telegram User ID (Admin)

1. Open Telegram and message **@userinfobot**
2. It replies with your numeric user ID (e.g. `7154670070`)
3. This is your `ADMIN_CHAT_ID`

### 4. Set Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
BOT_TOKEN=8283144990:AAHkT_VlQ...
PAYSTACK_SECRET_KEY=sk_live_xxx...
PAYSTACK_PUBLIC_KEY=pk_live_xxx...
ADMIN_CHAT_ID=7154670070
```

On **Replit**: go to the **Secrets** tab and add each variable there (no `.env` file needed).  
On **Render**: go to your service → **Environment** → add each variable.

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run Locally

```bash
cd bot
python main.py
```

The bot will start and log `Bot is running — polling for updates…`

---

## 🚀 Deployment

### Replit

1. Upload all files to a new Python Repl
2. Add secrets in the **Secrets** tab (not `.env`)
3. Set the **Run** command to: `cd bot && python main.py`
4. Click **Run** — Replit keeps it alive automatically

### Render

1. Push code to a GitHub repo
2. Create a new **Background Worker** service on [render.com](https://render.com)
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `cd bot && python main.py`
5. Add environment variables in the **Environment** tab
6. Deploy — Render will keep the bot running 24/7

---

## 🤖 Bot Commands

### User Commands
| Command | Description |
|---|---|
| `/start` | Open the main menu |

### Admin Commands (restricted to `ADMIN_CHAT_ID`)
| Command | Description |
|---|---|
| `/addmaterial` | Add a new material (interactive, step-by-step) |
| `/removematerial` | Deactivate a material from the shop |
| `/listmaterials` | Show all materials including inactive ones |
| `/listpayments` | Show recent payment records with stats |
| `/broadcast` | Send a message to all users |
| `/stats` | Quick revenue and order summary |

---

## 💳 Payment Flow

```
Student taps "Buy Now"
        ↓
Bot asks for email address
        ↓
Bot creates Paystack payment link
        ↓
Student pays on Paystack
        ↓
Student taps "I Have Paid — Verify Now"
        ↓
Bot verifies with Paystack API
        ↓
  ┌──── Success ────┐
  │ Token issued     │
  │ Record saved     │
  │ Admin notified   │
  └─────────────────┘
```

---

## 🔒 Security Notes

- All payments are verified server-side via the Paystack API (not just the client callback)
- Re-verifying a reference that is already paid returns the same token (no double-processing)
- Admin commands are locked to `ADMIN_CHAT_ID` — no other user can access them
- Secrets are stored in environment variables, never in code

---

## 📝 Customising Materials

The admin can add/remove materials entirely through the bot using `/addmaterial` and `/removematerial` — **no code editing required**.

On first run, 6 sample materials are automatically inserted into the database so you can test right away.

---

## 🆘 Support

If a student has trouble with their payment:
1. Ask for their **reference code** (e.g. `SM-7F3K2P1A2B3C4D`)
2. Check Paystack dashboard to confirm the payment
3. Use `/listpayments` in the bot to find their token
