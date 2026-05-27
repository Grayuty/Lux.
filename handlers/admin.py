"""
handlers/admin.py — Admin-only commands
/addmaterial, /removematerial, /listmaterials, /listpayments, /broadcast, /stats

All commands are restricted to ADMIN_CHAT_ID / ADMIN_TELEGRAM_ID.
"""

import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import database as db
from utils import format_naira

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversation states for /addmaterial
# ---------------------------------------------------------------------------
(
    ADD_NAME,
    ADD_PRICE,
    ADD_DESC,
) = range(3)

# ---------------------------------------------------------------------------
# Conversation states for /broadcast
# ---------------------------------------------------------------------------
BROADCAST_MSG = 10

# ---------------------------------------------------------------------------
# Conversation states for /removematerial
# ---------------------------------------------------------------------------
REMOVE_ID = 20


# ---------------------------------------------------------------------------
# Helper: check if the caller is the admin
# ---------------------------------------------------------------------------

def _get_admin_id() -> int | None:
    raw = os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_TELEGRAM_ID", "")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def _is_admin(update: Update) -> bool:
    admin_id = _get_admin_id()
    return admin_id is not None and update.effective_user.id == admin_id


async def _deny(update: Update):
    """Reply with an access-denied message."""
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg:
        await msg.reply_text("🚫 You are not authorized to use this command.")


# ---------------------------------------------------------------------------
# /addmaterial — multi-step conversation
# ---------------------------------------------------------------------------

async def add_material_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return ConversationHandler.END

    await update.message.reply_text(
        "➕ *Add New Material* (Step 1/3)\n\n"
        "What is the *name* of the material?\n\n"
        "_Type /cancel to abort at any time._",
        parse_mode="Markdown",
    )
    return ADD_NAME


async def add_material_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_mat_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Name: *{context.user_data['new_mat_name']}*\n\n"
        "➕ *Add New Material* (Step 2/3)\n\n"
        "What is the *price* in Naira? (whole number only, e.g. 2000)",
        parse_mode="Markdown",
    )
    return ADD_PRICE


async def add_material_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "").replace("₦", "")
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text(
            "❌ Please enter a valid price (whole number only, e.g. *2000*):",
            parse_mode="Markdown",
        )
        return ADD_PRICE

    context.user_data["new_mat_price"] = int(text)
    await update.message.reply_text(
        f"✅ Price: *{format_naira(context.user_data['new_mat_price'])}*\n\n"
        "➕ *Add New Material* (Step 3/3)\n\n"
        "Write a short *description* for this material:",
        parse_mode="Markdown",
    )
    return ADD_DESC


async def add_material_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text.strip()
    name = context.user_data.pop("new_mat_name")
    price = context.user_data.pop("new_mat_price")

    new_id = db.add_material(name=name, price=price, description=description)

    await update.message.reply_text(
        f"🎉 *Material Added Successfully!*\n\n"
        f"🆔 ID: `{new_id}`\n"
        f"📖 Name: *{name}*\n"
        f"💰 Price: *{format_naira(price)}*\n"
        f"📝 Description: {description}\n\n"
        "Students can now see and purchase this material.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /removematerial — ask for ID then deactivate
# ---------------------------------------------------------------------------

async def remove_material_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return ConversationHandler.END

    materials = db.get_all_materials()
    if not materials:
        await update.message.reply_text("No materials in the database yet.")
        return ConversationHandler.END

    lines = []
    for m in materials:
        status = "✅ Active" if m["active"] else "❌ Inactive"
        lines.append(f"ID `{m['id']}` — *{m['name']}* — {format_naira(m['price'])} — {status}")

    await update.message.reply_text(
        "🗑 *Remove Material*\n\n"
        + "\n".join(lines)
        + "\n\nSend the *ID* of the material to deactivate it:\n"
        "_Type /cancel to abort._",
        parse_mode="Markdown",
    )
    return REMOVE_ID


async def remove_material_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ Please send a valid numeric ID:")
        return REMOVE_ID

    material_id = int(text)
    mat = db.get_material(material_id)
    if not mat:
        await update.message.reply_text(
            f"❌ No material found with ID `{material_id}`. Try again:",
            parse_mode="Markdown",
        )
        return REMOVE_ID

    db.deactivate_material(material_id)
    await update.message.reply_text(
        f"✅ *Material Deactivated*\n\n"
        f"📖 *{mat['name']}* (ID `{material_id}`) has been set to *inactive*.\n"
        "Students will no longer see it in the shop.\n\n"
        "_Use /addmaterial if you need to add a replacement._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /listmaterials — show all materials (active + inactive) for admin
# ---------------------------------------------------------------------------

async def list_materials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return

    materials = db.get_all_materials()
    if not materials:
        await update.message.reply_text("No materials in the database yet.")
        return

    lines = ["📋 *All Materials*\n"]
    for m in materials:
        status = "✅" if m["active"] else "❌"
        lines.append(
            f"{status} ID `{m['id']}` — *{m['name']}*\n"
            f"   💰 {format_naira(m['price'])}  |  _{m['description'][:60]}…_"
        )

    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# /listpayments — show recent payment records
# ---------------------------------------------------------------------------

async def list_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return

    stats = db.get_payment_stats()
    payments = db.get_all_payments(limit=20)

    header = (
        f"💳 *Payment Records*\n\n"
        f"✅ Total Paid: {stats['total_paid']}\n"
        f"💰 Total Revenue: {format_naira(stats['total_revenue'])}\n"
        f"⏳ Pending: {stats['pending']}\n\n"
        "─────────────────────\n"
    )

    if not payments:
        await update.message.reply_text(header + "No payments recorded yet.")
        return

    lines = []
    for p in payments:
        icon = "✅" if p["status"] == "paid" else "⏳"
        lines.append(
            f"{icon} *{p['material_name']}*\n"
            f"   👤 {p['first_name']} (@{p['telegram_username']})\n"
            f"   💰 {format_naira(p['amount'])}  |  🎟 `{p['token']}`\n"
            f"   🔖 `{p['reference']}`\n"
            f"   📅 {p.get('paid_at') or p['created_at']}"
        )

    # Telegram message limit is 4096 chars — split if needed
    full_text = header + "\n\n".join(lines)
    if len(full_text) <= 4096:
        await update.message.reply_text(full_text, parse_mode="Markdown")
    else:
        await update.message.reply_text(header, parse_mode="Markdown")
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 2 > 4000:
                await update.message.reply_text(chunk, parse_mode="Markdown")
                chunk = ""
            chunk += line + "\n\n"
        if chunk:
            await update.message.reply_text(chunk, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /broadcast — send a message to all known users
# ---------------------------------------------------------------------------

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return ConversationHandler.END

    user_ids = db.get_all_user_ids()
    await update.message.reply_text(
        f"📢 *Broadcast Message*\n\n"
        f"This will send a message to *{len(user_ids)} users*.\n\n"
        "Type the message you want to broadcast:\n"
        "_Type /cancel to abort._",
        parse_mode="Markdown",
    )
    return BROADCAST_MSG


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text.strip()
    user_ids = db.get_all_user_ids()

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=f"📢 *Announcement*\n\n{message_text}",
                parse_mode="Markdown",
            )
            sent += 1
        except Exception as exc:
            logger.warning("Broadcast failed for %s: %s", uid, exc)
            failed += 1

    await update.message.reply_text(
        f"📢 *Broadcast Complete*\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Shared cancel handler for all admin conversations
# ---------------------------------------------------------------------------

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Action cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# /stats — quick summary
# ---------------------------------------------------------------------------

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await _deny(update)
        return

    s = db.get_payment_stats()
    materials = db.get_active_materials()
    await update.message.reply_text(
        f"📊 *Dashboard*\n\n"
        f"📚 Active Materials: {len(materials)}\n"
        f"✅ Successful Payments: {s['total_paid']}\n"
        f"💰 Total Revenue: {format_naira(s['total_revenue'])}\n"
        f"⏳ Pending Verifications: {s['pending']}",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Register all admin handlers
# ---------------------------------------------------------------------------

def register(app):
    """Attach all admin handlers to the bot Application."""
    cancel_cmd = CommandHandler("cancel", admin_cancel)

    # /addmaterial conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("addmaterial", add_material_start)],
        states={
            ADD_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_material_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_material_price)],
            ADD_DESC:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_material_desc)],
        },
        fallbacks=[cancel_cmd],
        per_message=False,
    )

    # /removematerial conversation
    remove_conv = ConversationHandler(
        entry_points=[CommandHandler("removematerial", remove_material_start)],
        states={
            REMOVE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_material_id)],
        },
        fallbacks=[cancel_cmd],
        per_message=False,
    )

    # /broadcast conversation
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)],
        },
        fallbacks=[cancel_cmd],
        per_message=False,
    )

    app.add_handler(add_conv)
    app.add_handler(remove_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CommandHandler("listmaterials", list_materials))
    app.add_handler(CommandHandler("listpayments", list_payments))
    app.add_handler(CommandHandler("stats", stats))
