import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash
from datetime import datetime

DB_PATH = 'quirol.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'cashier',
            security_question TEXT,
            security_answer TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            unit_price REAL NOT NULL,
            stock_kg REAL DEFAULT 0,
            low_stock_threshold REAL DEFAULT 50,
            shelf_life_days INTEGER DEFAULT 7
        );

        CREATE TABLE IF NOT EXISTS stock_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER REFERENCES products(id),
            quantity_kg REAL NOT NULL,
            remaining_kg REAL NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_code TEXT NOT NULL,
            total_amount REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS transaction_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id INTEGER REFERENCES transactions(id),
            product_id INTEGER REFERENCES products(id),
            quantity_kg REAL NOT NULL,
            unit_price REAL NOT NULL,
            subtotal REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS historical_sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            product_id INTEGER REFERENCES products(id),
            days_sold INTEGER,
            daily_avg_qty REAL,
            daily_avg_sales REAL,
            monthly_qty REAL,
            monthly_sales REAL
        );
    ''')

    # Migrate: add new columns if not exists
    for col_sql in [
        "ALTER TABLE users ADD COLUMN security_question TEXT",
        "ALTER TABLE users ADD COLUMN security_answer TEXT",
    ]:
        try:
            c.execute(col_sql)
            conn.commit()
        except Exception:
            pass

    # Migrate: add shelf_life_days if not exists
    try:
        c.execute("ALTER TABLE products ADD COLUMN shelf_life_days INTEGER DEFAULT 7")
        conn.commit()
    except Exception:
        pass

    conn.commit()
    conn.close()

def import_excel_data(excel_path):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM historical_sales")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    xl = pd.read_excel(excel_path, sheet_name=None)
    months = {'December': 'December 2025', 'January': 'January 2026', 'February': 'February 2026'}
    products_added = set()

    for sheet_name, df in xl.items():
        month_label = months.get(sheet_name, sheet_name)
        data = df.dropna(subset=['Item']).head(15)
        for _, row in data.iterrows():
            name = str(row['Item']).strip()
            price = float(row['Unit Price (₱)'])
            if name not in products_added:
                c.execute(
                    'INSERT OR IGNORE INTO products (name, unit_price, stock_kg, low_stock_threshold, shelf_life_days) VALUES (?, ?, 100, 50, 7)',
                    (name, price)
                )
                products_added.add(name)
            c.execute("SELECT id FROM products WHERE name = ?", (name,))
            product = c.fetchone()
            if not product:
                continue
            product_id = product[0]
            c.execute('''
                INSERT INTO historical_sales
                (month, product_id, days_sold, daily_avg_qty, daily_avg_sales, monthly_qty, monthly_sales)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                month_label, product_id,
                int(row['Days Sold']) if pd.notna(row['Days Sold']) else 0,
                float(row['Daily Avg Qty (kg)']) if pd.notna(row['Daily Avg Qty (kg)']) else 0,
                float(row['Daily Avg Sales (₱)']) if pd.notna(row['Daily Avg Sales (₱)']) else 0,
                float(row['Monthly Qty (kg)']) if pd.notna(row['Monthly Qty (kg)']) else 0,
                float(row['Monthly Sales (₱)']) if pd.notna(row['Monthly Sales (₱)']) else 0,
            ))

    conn.commit()
    conn.close()


def import_csv_data(csv_path):
    """Import day-to-day sales CSV as historical transactions."""
    import csv as csvlib
    from datetime import datetime

    conn = get_db()
    c = conn.cursor()

    # Skip if already imported
    c.execute("SELECT COUNT(*) FROM transactions WHERE transaction_code LIKE 'HIST-%'")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    # Get system user (admin)
    c.execute("SELECT id FROM users LIMIT 1")
    user = c.fetchone()
    if not user:
        conn.close()
        return
    user_id = user[0]

    # Read CSV
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csvlib.DictReader(f)
        rows = list(reader)

    # Group by date — each date becomes one historical transaction
    from collections import defaultdict
    by_date = defaultdict(list)
    for row in rows:
        date = row['Date'].strip()
        by_date[date].append(row)

    for date, items in sorted(by_date.items()):
        total = sum(float(r['Total Sales (₱)']) for r in items)
        code  = f"HIST-{date}"

        # Insert transaction
        cur = c.execute(
            "INSERT INTO transactions (transaction_code, total_amount, created_at, created_by) VALUES (?,?,?,?)",
            (code, round(total, 2), date + ' 00:00:00', user_id)
        )
        txn_id = cur.lastrowid

        for r in items:
            name  = r['Vegetable'].strip()
            qty   = float(r['Quantity (kg)'])
            price = float(r['Price per kg (₱)'])
            sub   = float(r['Total Sales (₱)'])

            # Get or create product
            c.execute("SELECT id FROM products WHERE name = ?", (name,))
            prod = c.fetchone()
            if not prod:
                c.execute(
                    "INSERT INTO products (name, unit_price, stock_kg, low_stock_threshold, shelf_life_days) VALUES (?,?,100,50,7)",
                    (name, price)
                )
                prod_id = c.lastrowid
            else:
                prod_id = prod[0]

            c.execute(
                "INSERT INTO transaction_items (transaction_id, product_id, quantity_kg, unit_price, subtotal) VALUES (?,?,?,?,?)",
                (txn_id, prod_id, qty, price, sub)
            )

    conn.commit()
    conn.close()
    print(f"Imported {len(by_date)} daily transactions from CSV.")

def seed_admin():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ('admin', generate_password_hash('admin123'), 'owner')
        )
        conn.commit()
    conn.close()

def fifo_deduct(conn, product_id, qty_needed):
    """Deduct qty_needed from oldest batches first (FIFO). Returns actual deducted."""
    batches = conn.execute(
        "SELECT id, remaining_kg FROM stock_batches WHERE product_id=? AND remaining_kg>0 ORDER BY received_at ASC",
        (product_id,)
    ).fetchall()
    total_deducted = 0.0
    for batch in batches:
        if qty_needed <= 0:
            break
        take = min(batch['remaining_kg'], qty_needed)
        conn.execute(
            "UPDATE stock_batches SET remaining_kg = remaining_kg - ? WHERE id = ?",
            (take, batch['id'])
        )
        qty_needed -= take
        total_deducted += take
    return total_deducted
