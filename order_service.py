"""Order processing service — the BEFORE version with deliberate problems."""

import json
import smtplib
from email.mime.text import MIMEText
from datetime import datetime


# Global config — no dependency injection
DB_HOST = "prod-db.internal"
SMTP_HOST = "mail.internal"
TAX_RATE = 0.19


def process_order(order_data, db_connection=None):
    """Process an incoming order: validate, store, send confirmation email."""

    # --- Validation (duplicated logic, no early returns) ---
    errors = []
    if "customer_email" not in order_data:
        errors.append("missing email")
    if "items" not in order_data:
        errors.append("missing items")
    if len(errors) > 0:
        print("Validation failed: " + str(errors))
        return {"status": "error", "errors": errors}

    # Check each item
    for item in order_data["items"]:
        if "name" not in item:
            errors.append("item missing name")
        if "price" not in item:
            errors.append("item missing price")
        if "quantity" not in item:
            errors.append("item missing quantity")
        # Duplicate: check again after the loop
    if len(errors) > 0:
        print("Validation failed: " + str(errors))
        return {"status": "error", "errors": errors}

    # --- Price calculation (inline, no helper, tax logic mixed in) ---
    subtotal = 0
    for item in order_data["items"]:
        item_total = item["price"] * item["quantity"]
        subtotal = subtotal + item_total
    tax = subtotal * TAX_RATE
    total = subtotal + tax

    # --- Store to database (raw SQL, no error handling) ---
    if db_connection is None:
        import psycopg2
        db_connection = psycopg2.connect(host=DB_HOST, database="orders")

    cursor = db_connection.cursor()
    cursor.execute(
        "INSERT INTO orders (customer_email, items_json, subtotal, tax, total, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
        (order_data["customer_email"], json.dumps(order_data["items"]), subtotal, tax, total, datetime.now())
    )
    db_connection.commit()
    order_id = cursor.lastrowid

    # --- Send confirmation email (inline, no template, duplicated formatting) ---
    items_text = ""
    for item in order_data["items"]:
        items_text += f"  - {item['name']}: {item['quantity']}x {item['price']:.2f} EUR\n"

    email_body = f"""Dear Customer,

Thank you for your order #{order_id}!

Your items:
{items_text}
Subtotal: {subtotal:.2f} EUR
Tax (19%): {tax:.2f} EUR
Total: {total:.2f} EUR

We will process your order shortly.

Best regards,
The Shop Team"""

    msg = MIMEText(email_body)
    msg["Subject"] = f"Order Confirmation #{order_id}"
    msg["From"] = "shop@example.com"
    msg["To"] = order_data["customer_email"]

    server = smtplib.SMTP(SMTP_HOST)
    server.send_message(msg)
    server.quit()

    print(f"Order {order_id} processed successfully")
    return {"status": "success", "order_id": order_id, "total": total}


def cancel_order(order_id, db_connection=None):
    """Cancel an order and send a cancellation email to the customer."""

    if db_connection is None:
        import psycopg2
        db_connection = psycopg2.connect(host=DB_HOST, database="orders")

    cursor = db_connection.cursor()
    cursor.execute("SELECT customer_email, status FROM orders WHERE id = %s", (order_id,))
    row = cursor.fetchone()

    if row is None:
        return {"status": "error", "errors": ["order not found"]}

    customer_email, current_status = row
    if current_status == "cancelled":
        return {"status": "error", "errors": ["order already cancelled"]}

    cursor.execute("UPDATE orders SET status = %s WHERE id = %s", ("cancelled", order_id))
    db_connection.commit()

    email_body = f"""Dear Customer,

Your order #{order_id} has been cancelled.

If you did not request this cancellation, please contact us if you have any questions.

Best regards,
The Shop Team"""

    msg = MIMEText(email_body)
    msg["Subject"] = f"Order Cancellation #{order_id}"
    msg["From"] = "shop@example.com"
    msg["To"] = customer_email

    server = smtplib.SMTP(SMTP_HOST)
    server.send_message(msg)
    server.quit()

    print(f"Order {order_id} cancelled successfully")
    return {"status": "success", "order_id": order_id}


def get_order_summary(order_id, db_connection=None):
    """Get order summary — duplicates price formatting from above."""

    if db_connection is None:
        import psycopg2
        db_connection = psycopg2.connect(host=DB_HOST, database="orders")

    cursor = db_connection.cursor()
    cursor.execute("SELECT customer_email, items_json, subtotal, tax, total FROM orders WHERE id = %s", (order_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    items = json.loads(row[1])

    # Duplicated formatting logic
    items_text = ""
    for item in items:
        items_text += f"  - {item['name']}: {item['quantity']}x {item['price']:.2f} EUR\n"

    return {
        "order_id": order_id,
        "customer_email": row[0],
        "items_formatted": items_text,
        "subtotal": f"{row[2]:.2f} EUR",
        "tax": f"{row[3]:.2f} EUR",
        "total": f"{row[4]:.2f} EUR",
    }
