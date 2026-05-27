"""
Run this ONCE after first login to set up your account recovery security question.
Usage: py setup_recovery.py
"""
import sqlite3
from werkzeug.security import generate_password_hash

DB_PATH = 'quirol.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

print("=" * 50)
print("  Quirol Veggies — Recovery Setup")
print("=" * 50)
print()

conn = get_db()
owners = conn.execute("SELECT id, username FROM users WHERE role='owner'").fetchall()

if not owners:
    print("No owner accounts found. Run py app.py first.")
    conn.close()
    exit()

print("Owner accounts found:")
for i, o in enumerate(owners):
    print(f"  {i+1}. {o['username']}")

print()
username = input("Enter your owner username: ").strip()
owner = conn.execute("SELECT * FROM users WHERE username=? AND role='owner'", (username,)).fetchone()

if not owner:
    print("Owner account not found.")
    conn.close()
    exit()

print()
print("Choose a security question:")
questions = [
    "What is your mother's maiden name?",
    "What was the name of your first pet?",
    "What city were you born in?",
    "What is your oldest sibling's middle name?",
    "What was the name of your elementary school?",
]
for i, q in enumerate(questions):
    print(f"  {i+1}. {q}")

print()
choice = input("Enter number (1-5): ").strip()
try:
    idx = int(choice) - 1
    question = questions[idx]
except:
    print("Invalid choice.")
    conn.close()
    exit()

answer = input(f"Your answer to '{question}': ").strip().lower()
if not answer:
    print("Answer cannot be empty.")
    conn.close()
    exit()

conn.execute(
    "UPDATE users SET security_question=?, security_answer=? WHERE id=?",
    (question, generate_password_hash(answer), owner['id'])
)
conn.commit()
conn.close()

print()
print(f"Recovery question set for '{username}'.")
print("Remember your answer — it's needed to reset your password.")
print("=" * 50)
