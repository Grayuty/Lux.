"""
handlers/user.py — All user-facing bot handlers
Covers: /start, browse, cart management, checkout, payment verification
"""

import logging
import os
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import database as db
import paystack as ps
from utils import format_naira, generate_token

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cart_badge(user_id: int) -> str:
    """Return a cart count badge string, e.g. ' (3)' or '' if empty."""
    count = db.cart_item_count(user_id)
    return f" ({count})" if count else ""


def _build_main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    count = db.cart_item_count(user_id)
    cart_label = f"🛒 View Cart ({count} item{'s' if count != 1 else ''})" if count else "🛒 View Cart"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")],
        [InlineKeyboardButton(cart_label,            callback_data="view_cart")],
        [InlineKeyboardButton("ℹ️ How It Works",     callback_data="how_it_works")],
    ])


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "")
    context.user_data.pop("awaiting_checkout_email", None)

    await update.message.reply_text(
        f"👋 Welcome, *{user.first_name}*!\n\n"
        "📚 *Study Materials Shop*\n\n"
        "Browse materials, add them to your cart, and pay once for everything.\n"
        "You'll receive a *pickup token* after payment to collect your printed materials.\n\n"
        "Tap a button below to get started:",
        parse_mode="Markdown",
        reply_markup=_build_main_menu_keyboard(user.id),
    )


# ---------------------------------------------------------------------------
# How it works
# ---------------------------------------------------------------------------

async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "ℹ️ *How It Works*\n\n"
        "1️⃣ Browse available study materials\n"
        "2️⃣ Tap *Add to Cart* on the ones you want\n"
        "3️⃣ Open your cart and tap *Proceed to Payment*\n"
        "4️⃣ Enter your email to get a Paystack link\n"
        "5️⃣ Complete payment on Paystack\n"
        "6️⃣ Return here and tap *I Have Paid — Verify*\n"
        "7️⃣ Receive your *receipt token* 🎟\n"
        "8️⃣ Show the token to the class rep to collect all your materials\n\n"
        "_All transactions are secured by Paystack._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")],
            [InlineKeyboardButton("🏠 Main Menu",        callback_data="main_menu")],
        ]),
    )


# ---------------------------------------------------------------------------
# Main menu (back button)
# ---------------------------------------------------------------------------

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("awaiting_checkout_email", None)
    user_id = update.effective_user.id
    await query.edit_message_text(
        "🏠 *Main Menu* — What would you like to do?",
        parse_mode="Markdown",
        reply_markup=_build_main_menu_keyboard(user_id),
    )


# ---------------------------------------------------------------------------
# Browse materials
# ---------------------------------------------------------------------------

async def browse_materials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    materials = db.get_active_materials()
    user_id = update.effective_user.id

    if not materials:
        await query.edit_message_text(
            "😔 No materials available right now. Check back soon!",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
            ),
        )
        return

    keyboard = []
    for mat in materials:
        keyboard.append([InlineKeyboardButton(
            f"📖 {mat['name']}  —  {format_naira(mat['price'])}",
            callback_data=f"mat_{mat['id']}",
        )])

    count = db.cart_item_count(user_id)
    cart_label = f"🛒 View Cart ({count})" if count else "🛒 View Cart"
    keyboard.append([
        InlineKeyboardButton(cart_label, callback_data="view_cart"),
        InlineKeyboardButton("🏠 Menu",  callback_data="main_menu"),
    ])

    await query.edit_message_text(
        "📚 *Available Study Materials*\n\nTap a material to see details and add it to your cart:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------------------------------------------------------------------
# Material detail — shows "Add to Cart" button
# ---------------------------------------------------------------------------

async def material_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    material_id = int(query.data.replace("mat_", ""))
    mat = db.get_material(material_id)
    if not mat or not mat["active"]:
        await query.edit_message_text("❌ This material is no longer available.")
        return

    user_id = update.effective_user.id
    count = db.cart_item_count(user_id)
    cart_label = f"🛒 View Cart ({count})" if count else "🛒 View Cart"

    await query.edit_message_text(
        f"📖 *{mat['name']}*\n\n"
        f"_{mat['description']}_\n\n"
        f"💰 *Price:* {format_naira(mat['price'])}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart_add_{mat['id']}")],
            [InlineKeyboardButton(cart_label,       callback_data="view_cart")],
            [InlineKeyboardButton("⬅️ Back",        callback_data="browse_materials")],
        ]),
    )


# ---------------------------------------------------------------------------
# Cart — Add item
# ---------------------------------------------------------------------------

async def cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add one unit of a material to the user's cart."""
    query = update.callback_query
    await query.answer()

    material_id = int(query.data.replace("cart_add_", ""))
    mat = db.get_material(material_id)
    if not mat or not mat["active"]:
        await query.edit_message_text("❌ This material is no longer available.")
        return

    user_id = update.effective_user.id
    result = db.add_to_cart(user_id, material_id)
    qty = result["quantity"]
    total = db.calculate_cart_total(user_id)
    count = db.cart_item_count(user_id)

    await query.edit_message_text(
        f"✅ *Added to Cart!*\n\n"
        f"📖 {mat['name']}\n"
        f"💰 {format_naira(mat['price'])} × {qty} = *{format_naira(mat['price'] * qty)}*\n\n"
        f"🛒 Cart total: *{format_naira(total)}* ({count} item{'s' if count != 1 else ''})\n\n"
        "Continue browsing or go to your cart to check out:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🛒 View Cart ({count})", callback_data="view_cart")],
            [InlineKeyboardButton("📚 Continue Shopping",     callback_data="browse_materials")],
            [InlineKeyboardButton("🏠 Main Menu",             callback_data="main_menu")],
        ]),
    )


# ---------------------------------------------------------------------------
# Cart — View cart
# ---------------------------------------------------------------------------

async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display the user's cart with all items, totals, and action buttons."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    items = db.get_cart(user_id)

    if not items:
        await query.edit_message_text(
            "🛒 *Your Cart is Empty*\n\n"
            "Browse materials and tap *Add to Cart* to get started.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")],
                [InlineKeyboardButton("🏠 Main Menu",        callback_data="main_menu")],
            ]),
        )
        return

    total = sum(i["subtotal"] for i in items)

    # Build cart summary text
    lines = ["🛒 *Your Cart*\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. *{item['name']}*\n"
            f"   {format_naira(item['price'])} × {item['quantity']} = *{format_naira(item['subtotal'])}*"
        )
    lines.append(f"\n💰 *Total: {format_naira(total)}*")

    # Build buttons: one "Remove" row per item, then action buttons
    keyboard = []
    for item in items:
        keyboard.append([InlineKeyboardButton(
            f"❌ Remove {item['name'][:30]}",
            callback_data=f"cart_remove_{item['material_id']}",
        )])
    keyboard.append([InlineKeyboardButton("🗑 Clear Cart", callback_data="cart_clear")])
    keyboard.append([
        InlineKeyboardButton("💳 Proceed to Payment", callback_data="cart_checkout"),
    ])
    keyboard.append([InlineKeyboardButton("📚 Continue Shopping", callback_data="browse_materials")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------------------------------------------------------------------
# Cart — Remove one item
# ---------------------------------------------------------------------------

async def cart_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    material_id = int(query.data.replace("cart_remove_", ""))
    db.remove_from_cart(user_id, material_id)

    # Refresh the cart view in-place
    items = db.get_cart(user_id)
    if not items:
        await query.edit_message_text(
            "🛒 *Cart is now empty.*\n\nBrowse materials to add items.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")],
                [InlineKeyboardButton("🏠 Main Menu",        callback_data="main_menu")],
            ]),
        )
        return

    total = sum(i["subtotal"] for i in items)
    lines = ["🛒 *Your Cart* _(updated)_\n"]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. *{item['name']}*\n"
            f"   {format_naira(item['price'])} × {item['quantity']} = *{format_naira(item['subtotal'])}*"
        )
    lines.append(f"\n💰 *Total: {format_naira(total)}*")

    keyboard = []
    for item in items:
        keyboard.append([InlineKeyboardButton(
            f"❌ Remove {item['name'][:30]}",
            callback_data=f"cart_remove_{item['material_id']}",
        )])
    keyboard.append([InlineKeyboardButton("🗑 Clear Cart", callback_data="cart_clear")])
    keyboard.append([InlineKeyboardButton("💳 Proceed to Payment", callback_data="cart_checkout")])
    keyboard.append([InlineKeyboardButton("📚 Continue Shopping", callback_data="browse_materials")])

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ---------------------------------------------------------------------------
# Cart — Clear entire cart
# ---------------------------------------------------------------------------

async def cart_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🗑 Cart cleared.")

    user_id = update.effective_user.id
    db.clear_cart(user_id)

    await query.edit_message_text(
        "🗑 *Cart Cleared*\n\nAll items have been removed from your cart.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")],
            [InlineKeyboardButton("🏠 Main Menu",        callback_data="main_menu")],
        ]),
    )


# ---------------------------------------------------------------------------
# Cart — Checkout (ask for email)
# ---------------------------------------------------------------------------

async def cart_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Validate the cart is non-empty, then ask the user to type their email.
    The email is caught by handle_text() which checks awaiting_checkout_email.
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    items = db.get_cart(user_id)

    if not items:
        await query.edit_message_text(
            "🛒 Your cart is empty. Add materials before checking out.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 Browse Materials", callback_data="browse_materials")]
            ]),
        )
        return

    total = sum(i["subtotal"] for i in items)
    count = sum(i["quantity"] for i in items)

    # Flag that the next text message is the email
    context.user_data["awaiting_checkout_email"] = True

    await query.edit_message_text(
        f"💳 *Checkout*\n\n"
        f"🛒 {count} item{'s' if count != 1 else ''} — Total: *{format_naira(total)}*\n\n"
        "Please *type your email address* below so we can generate your Paystack payment link:\n\n"
        "_Type /cancel to go back._",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Text handler — catches email for checkout (and unknown messages)
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catch-all text handler.
    If awaiting_checkout_email is set in user_data, treat the message as an email
    and generate the Paystack cart payment link.
    """
    text_lower = update.message.text.strip().lower()
    if text_lower in ("/cancel", "cancel"):
        context.user_data.pop("awaiting_checkout_email", None)
        await update.message.reply_text(
            "❌ Cancelled. Type /start to go back to the menu."
        )
        return

    if not context.user_data.get("awaiting_checkout_email"):
        await update.message.reply_text(
            "👋 Type /start to browse materials and build your cart."
        )
        return

    # --- Process email ---
    email = update.message.text.strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        await update.message.reply_text(
            "❌ That doesn't look like a valid email.\n"
            "Please enter a valid address (e.g. *yourname@gmail.com*):",
            parse_mode="Markdown",
        )
        return  # Stay waiting

    user = update.effective_user
    items = db.get_cart(user.id)

    if not items:
        context.user_data.pop("awaiting_checkout_email", None)
        await update.message.reply_text(
            "⚠️ Your cart is empty. Please browse and add items first.\n"
            "Type /start to begin."
        )
        return

    total = sum(i["subtotal"] for i in items)
    reference = f"SM-{uuid.uuid4().hex[:14].upper()}"
    token = generate_token()  # e.g. MAT-7F3K2P

    # Cart snapshot for the payment record
    cart_snapshot = [
        {
            "name":     item["name"],
            "price":    item["price"],
            "quantity": item["quantity"],
            "subtotal": item["subtotal"],
        }
        for item in items
    ]

    # Build a readable summary for Paystack metadata
    items_summary = ", ".join(
        f"{i['name']} ×{i['quantity']}" for i in items
    )

    result = ps.initialize_payment(
        email=email,
        amount_naira=total,
        reference=reference,
        metadata={
            "user_id":  user.id,
            "username": user.username or "N/A",
            "items":    items_summary,
            "token":    token,
        },
    )

    if not result.get("status"):
        await update.message.reply_text(
            f"❌ Could not create payment link.\n"
            f"Reason: {result.get('message', 'Unknown error')}\n\n"
            "Please try again or contact the class rep."
        )
        context.user_data.pop("awaiting_checkout_email", None)
        return

    payment_url = result["data"]["authorization_url"]

    # Save payment record with cart snapshot
    db.create_payment(
        telegram_user_id=user.id,
        telegram_username=user.username or "N/A",
        first_name=user.first_name or "N/A",
        amount=total,
        reference=reference,
        token=token,
        cart_snapshot=cart_snapshot,
        material_id=0,
        material_name=f"Cart ({len(items)} item{'s' if len(items) != 1 else ''})",
    )

    context.user_data.pop("awaiting_checkout_email", None)

    # Build cart summary for the message
    lines = []
    for item in items:
        lines.append(f"• {item['name']} ×{item['quantity']} — {format_naira(item['subtotal'])}")
    cart_text = "\n".join(lines)

    await update.message.reply_text(
        f"✅ *Payment Link Created!*\n\n"
        f"🛒 *Your Order:*\n{cart_text}\n\n"
        f"💰 *Total: {format_naira(total)}*\n"
        f"🔖 Reference: `{reference}`\n\n"
        "1️⃣ Tap *Pay Now* to complete payment on Paystack.\n"
        "2️⃣ Come back and tap *I Have Paid* to receive your token.\n\n"
        "_Keep this message — the reference is your proof of purchase._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Now on Paystack",      url=payment_url)],
            [InlineKeyboardButton("✅ I Have Paid — Verify Now", callback_data=f"verify_{reference}")],
            [InlineKeyboardButton("❌ Cancel",                   callback_data="main_menu")],
        ]),
    )


# ---------------------------------------------------------------------------
# /cancel command
# ---------------------------------------------------------------------------

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_checkout_email", None)
    await update.message.reply_text(
        "❌ Cancelled. Type /start to go back to the menu."
    )


# ---------------------------------------------------------------------------
# Payment verification
# ---------------------------------------------------------------------------

async def verify_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Checking your payment…")

    reference = query.data.replace("verify_", "")

    # Duplicate-payment guard
    if db.payment_already_verified(reference):
        record = db.get_payment_by_reference(reference)
        await query.edit_message_text(
            f"✅ *Already Confirmed*\n\n"
            f"Your receipt token is:\n\n"
            f"🎟  `{record['token']}`\n\n"
            "Show this to the class rep to collect your materials.",
            parse_mode="Markdown",
        )
        return

    result = ps.verify_payment(reference)

    if result.get("status") and result["data"]["status"] == "success":
        record = db.mark_payment_paid(reference)

        # Clear the cart now that payment is confirmed
        db.clear_cart(record["telegram_user_id"])

        # Build cart breakdown for the success message
        snapshot = record.get("cart_snapshot") or []
        if snapshot:
            lines = [f"• {i['name']} ×{i['quantity']} — {format_naira(i['subtotal'])}" for i in snapshot]
            cart_text = "\n".join(lines) + f"\n\n💰 *Total Paid: {format_naira(record['amount'])}*"
        else:
            cart_text = f"💰 *Amount Paid: {format_naira(record['amount'])}*"

        await query.edit_message_text(
            f"🎉 *Payment Confirmed!*\n\n"
            f"🛒 *Items Purchased:*\n{cart_text}\n\n"
            f"🎟 *Your Receipt Token:*\n"
            f"┌────────────────────┐\n"
            f"│   `{record['token']}`   │\n"
            f"└────────────────────┘\n\n"
            "Show this token to the class rep to collect *all* your materials.\n"
            "_Screenshot this message for your records._",
            parse_mode="Markdown",
        )

        await _notify_admin(context, record)

    else:
        txn_status = result.get("data", {}).get("status", "unknown")
        await query.edit_message_text(
            f"⏳ *Payment Not Confirmed Yet*\n\n"
            f"Paystack status: *{txn_status}*\n\n"
            "Complete your payment on Paystack then tap *Try Again*.\n\n"
            f"_Reference: `{reference}`_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again",  callback_data=f"verify_{reference}")],
                [InlineKeyboardButton("🏠 Main Menu",  callback_data="main_menu")],
            ]),
        )


# ---------------------------------------------------------------------------
# Admin notification (with full cart breakdown)
# ---------------------------------------------------------------------------

async def _notify_admin(context: ContextTypes.DEFAULT_TYPE, record: dict):
    admin_id = os.environ.get("ADMIN_CHAT_ID") or os.environ.get("ADMIN_TELEGRAM_ID", "")
    if not admin_id:
        return

    snapshot = record.get("cart_snapshot") or []
    if snapshot:
        item_lines = "\n".join(
            f"  • {i['name']} ×{i['quantity']} — {format_naira(i['subtotal'])}"
            for i in snapshot
        )
        cart_breakdown = f"\n🛒 *Items Purchased:*\n{item_lines}\n"
    else:
        cart_breakdown = ""

    try:
        await context.bot.send_message(
            chat_id=int(admin_id),
            text=(
                f"🛍 *New Payment Received!*\n\n"
                f"👤 Buyer: {record['first_name']} (@{record['telegram_username']})\n"
                f"🆔 User ID: `{record['telegram_user_id']}`\n"
                f"{cart_breakdown}"
                f"💰 Total: *{format_naira(record['amount'])}*\n"
                f"🎟 Token: `{record['token']}`\n"
                f"🔖 Reference: `{record['reference']}`\n"
                f"📅 Paid At: {record['paid_at']}"
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("Failed to notify admin: %s", exc)


# ---------------------------------------------------------------------------
# Fallback for unrecognised callback queries (e.g. old buy_X buttons)
# ---------------------------------------------------------------------------

async def _unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Catch-all for callback queries that no registered handler matched.
    This handles old inline buttons from previous bot versions gracefully.
    """
    query = update.callback_query
    await query.answer("⚠️ This button is outdated. Please tap /start to begin fresh.")
    try:
        await query.edit_message_text(
            "⚠️ *This button is no longer valid.*\n\n"
            "Please type /start to open the main menu and try again.",
            parse_mode="Markdown",
        )
    except Exception:
        pass  # Message may already be deleted or too old to edit


# ---------------------------------------------------------------------------
# Register all handlers
# ---------------------------------------------------------------------------

def register(app):
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("cancel", cancel))

    # Navigation
    app.add_handler(CallbackQueryHandler(browse_materials, pattern="^browse_materials$"))
    app.add_handler(CallbackQueryHandler(how_it_works,     pattern="^how_it_works$"))
    app.add_handler(CallbackQueryHandler(main_menu,        pattern="^main_menu$"))

    # Material detail
    app.add_handler(CallbackQueryHandler(material_detail, pattern=r"^mat_\d+$"))

    # Cart actions
    app.add_handler(CallbackQueryHandler(cart_add,      pattern=r"^cart_add_\d+$"))
    app.add_handler(CallbackQueryHandler(view_cart,     pattern="^view_cart$"))
    app.add_handler(CallbackQueryHandler(cart_remove,   pattern=r"^cart_remove_\d+$"))
    app.add_handler(CallbackQueryHandler(cart_clear,    pattern="^cart_clear$"))
    app.add_handler(CallbackQueryHandler(cart_checkout, pattern="^cart_checkout$"))

    # Payment verification
    app.add_handler(CallbackQueryHandler(verify_payment, pattern=r"^verify_SM-"))

    # Text input — must be last (catches email for checkout)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Catch-all for any unrecognised callback queries (e.g. old buy_X buttons)
    app.add_handler(CallbackQueryHandler(_unknown_callback))
