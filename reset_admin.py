"""
Use this if you forgot your owner password.
Usage: py reset_admin.py
"""
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = 'quirol.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

print("=" * 50)
print("  Quirol Veggies — Password Reset")
print("=" * 50)
print()

conn = get_db()
owners = conn.execute("SELECT * FROM users WHERE role='owner'").fetchall()

if not owners:
    print("No owner accounts found.")
    conn.close()
    exit()

print("Owner accounts:")
for o in owners:
    print(f"  - {o['username']}")

print()
username = input("Enter your owner username: ").strip()
owner = conn.execute("SELECT * FROM users WHERE username=? AND role='owner'", (username,)).fetchone()

if not owner:
    print("Owner account not found.")
    conn.close()
    exit()

if not owner['security_question']:
    print()
    print("No recovery question set for this account.")
    print("Run 'py setup_recovery.py' first while you still have access.")
    conn.close()
    exit()

print()
print(f"Security question: {owner['security_question']}")
answer = input("Your answer: ").strip().lower()

if not check_password_hash(owner['security_answer'], answer):
    print()
    print("Incorrect answer. Password not reset.")
    conn.close()
    exit()

print()
new_pw = input("Enter new password (min 6 characters): ").strip()
if len(new_pw) < 6:
    print("Password too short.")
    conn.close()
    exit()

confirm = input("Confirm new password: ").strip()
if new_pw != confirm:
    print("Passwords do not match.")
    conn.close()
    exit()

conn.execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(new_pw), owner['id']))
conn.commit()
conn.close()

print()
print(f"Password for '{username}' has been reset.")
print("You can now log in with your new password.")
print("=" * 50)
