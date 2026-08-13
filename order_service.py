"""Order processing service."""

import json
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

DB_HOST = "prod-db.internal"
DB_NAME = "orders"
SMTP_HOST = "mail.internal"
SENDER_EMAIL = "shop@example.com"
TAX_RATE = 0.19

REQUIRED_ORDER_FIELDS = ("customer_email", "items")
REQUIRED_ITEM_FIELDS = ("name", "price", "quantity")


def process_order(order_data, db_connection=None):
    """Process an incoming order: validate, store, send confirmation email."""
    errors = _validate_order(order_data)
    if errors:
        logger.warning("Validation failed: %s", errors)
        return {"status": "error", "errors": errors}

    subtotal, tax, total = _calculate_totals(order_data["items"])

    db_connection = db_connection or _connect_db()
    order_id = _store_order(db_connection, order_data, subtotal, tax, total)

    _send_confirmation_email(
        order_data["customer_email"], order_id, order_data["items"], subtotal, tax, total
    )

    logger.info("Order %s processed successfully", order_id)
    return {"status": "success", "order_id": order_id, "total": total}


def get_order_summary(order_id, db_connection=None):
    """Get a formatted summary of a stored order, or None if not found."""
    db_connection = db_connection or _connect_db()

    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT customer_email, items_json, subtotal, tax, total FROM orders WHERE id = %s",
        (order_id,),
    )
    row = cursor.fetchone()

    if row is None:
        return None

    customer_email, items_json, subtotal, tax, total = row

    return {
        "order_id": order_id,
        "customer_email": customer_email,
        "items_formatted": _format_items(json.loads(items_json)),
        "subtotal": _format_amount(subtotal),
        "tax": _format_amount(tax),
        "total": _format_amount(total),
    }


def _validate_order(order_data):
    """Return a list of validation errors (empty if the order is valid)."""
    errors = [
        f"missing {field.replace('customer_', '')}"
        for field in REQUIRED_ORDER_FIELDS
        if field not in order_data
    ]
    if errors:
        return errors

    for item in order_data["items"]:
        errors.extend(
            f"item missing {field}" for field in REQUIRED_ITEM_FIELDS if field not in item
        )
    return errors


def _calculate_totals(items):
    """Return (subtotal, tax, total) for the given items."""
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    tax = subtotal * TAX_RATE
    return subtotal, tax, subtotal + tax


def _connect_db():
    import psycopg2

    return psycopg2.connect(host=DB_HOST, database=DB_NAME)


def _store_order(db_connection, order_data, subtotal, tax, total):
    """Insert the order and return its id."""
    cursor = db_connection.cursor()
    cursor.execute(
        "INSERT INTO orders (customer_email, items_json, subtotal, tax, total, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (
            order_data["customer_email"],
            json.dumps(order_data["items"]),
            subtotal,
            tax,
            total,
            datetime.now(),
        ),
    )
    db_connection.commit()
    return cursor.lastrowid


def _format_amount(amount):
    return f"{amount:.2f} EUR"


def _format_items(items):
    return "".join(
        f"  - {item['name']}: {item['quantity']}x {item['price']:.2f} EUR\n" for item in items
    )


def _send_confirmation_email(recipient, order_id, items, subtotal, tax, total):
    body = f"""Dear Customer,

Thank you for your order #{order_id}!

Your items:
{_format_items(items)}
Subtotal: {_format_amount(subtotal)}
Tax ({TAX_RATE:.0%}): {_format_amount(tax)}
Total: {_format_amount(total)}

We will process your order shortly.

Best regards,
The Shop Team"""

    msg = MIMEText(body)
    msg["Subject"] = f"Order Confirmation #{order_id}"
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient

    server = smtplib.SMTP(SMTP_HOST)
    try:
        server.send_message(msg)
    finally:
        server.quit()
