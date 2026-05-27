import sqlite3
conn = sqlite3.connect('quirol.db')
conn.execute("UPDATE stock_batches SET expires_at = '2026-12-31 00:00:00' WHERE product_id = (SELECT id FROM products WHERE name = 'Ampalaya') AND remaining_kg > 0")
conn.commit()
conn.close()
print('Done!')