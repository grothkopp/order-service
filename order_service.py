"""Order processing service: validates, prices, stores, and confirms orders."""

import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime

DB_HOST = "prod-db.internal"
SMTP_HOST = "mail.internal"
TAX_RATE = 0.19

REQUIRED_ORDER_FIELDS = ("customer_email", "items")
REQUIRED_ITEM_FIELDS = ("name", "price", "quantity")


def _validate_order(order_data):
    """Return a list of validation error messages for order_data."""
    errors = [f"missing {field}" for field in REQUIRED_ORDER_FIELDS if field not in order_data]
    if errors:
        return errors

    for item in order_data["items"]:
        errors.extend(f"item missing {field}" for field in REQUIRED_ITEM_FIELDS if field not in item)
    return errors


def _calculate_totals(items):
    """Return (subtotal, tax, total) for a list of order items."""
    subtotal = sum(item["price"] * item["quantity"] for item in items)
    tax = subtotal * TAX_RATE
    return subtotal, tax, subtotal + tax


def _format_items(items):
    """Render order items as an indented, human-readable block."""
    return "".join(f"  - {item['name']}: {item['quantity']}x {item['price']:.2f} EUR\n" for item in items)


def _get_db_connection(db_connection):
    if db_connection is not None:
        return db_connection
    import psycopg2

    return psycopg2.connect(host=DB_HOST, database="orders")


def _insert_order(db_connection, order_data, subtotal, tax, total):
    cursor = db_connection.cursor()
    try:
        cursor.execute(
            "INSERT INTO orders (customer_email, items_json, subtotal, tax, total, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
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
    except Exception:
        db_connection.rollback()
        raise
    return cursor.lastrowid


def _build_confirmation_email(order_id, customer_email, items, subtotal, tax, total):
    email_body = f"""Dear Customer,

Thank you for your order #{order_id}!

Your items:
{_format_items(items)}
Subtotal: {subtotal:.2f} EUR
Tax ({TAX_RATE * 100:.0f}%): {tax:.2f} EUR
Total: {total:.2f} EUR

We will process your order shortly.

Best regards,
The Shop Team"""

    msg = MIMEText(email_body)
    msg["Subject"] = f"Order Confirmation #{order_id}"
    msg["From"] = "shop@example.com"
    msg["To"] = customer_email
    return msg


def _send_email(msg):
    server = smtplib.SMTP(SMTP_HOST)
    try:
        server.send_message(msg)
    finally:
        server.quit()


def process_order(order_data, db_connection=None):
    """Process an incoming order: validate, store, send confirmation email."""
    errors = _validate_order(order_data)
    if errors:
        print("Validation failed: " + str(errors))
        return {"status": "error", "errors": errors}

    items = order_data["items"]
    subtotal, tax, total = _calculate_totals(items)

    db_connection = _get_db_connection(db_connection)
    order_id = _insert_order(db_connection, order_data, subtotal, tax, total)

    email = _build_confirmation_email(order_id, order_data["customer_email"], items, subtotal, tax, total)
    _send_email(email)

    print(f"Order {order_id} processed successfully")
    return {"status": "success", "order_id": order_id, "total": total}


def get_order_summary(order_id, db_connection=None):
    """Return a formatted summary for a stored order, or None if it doesn't exist."""
    db_connection = _get_db_connection(db_connection)
    cursor = db_connection.cursor()
    cursor.execute(
        "SELECT customer_email, items_json, subtotal, tax, total FROM orders WHERE id = %s",
        (order_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None

    customer_email, items_json, subtotal, tax, total = row
    items = json.loads(items_json)

    return {
        "order_id": order_id,
        "customer_email": customer_email,
        "items_formatted": _format_items(items),
        "subtotal": f"{subtotal:.2f} EUR",
        "tax": f"{tax:.2f} EUR",
        "total": f"{total:.2f} EUR",
    }
