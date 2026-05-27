# 🥦 Ajon Veggies Distribution System

A web-based **Business Intelligence and Point-of-Sale system** for a vegetable distribution business. Built with Python (Flask) and SQLite, it tracks sales, manages inventory, generates reports, and provides analytics — all from a clean dashboard.

---

## 📑 Table of Contents
- [Preview](#-preview)
- [Features](#-features)
- [Tech Stack](#%EF%B8%8F-tech-stack)
- [Setup](#%EF%B8%8F-setup)
- [Default Login](#-default-login)
- [Project Structure](#-project-structure)
- [Notes](#-notes)
- [Developer](#%E2%80%8D-developer)
---

## 📸 Preview
> Dashboard showing total revenue, daily sales trend, and top 5 best-selling products.

---

## ✨ Features
- 📊 **Dashboard** — Total revenue, today's sales, product count, low stock alerts, monthly & daily sales charts
- 🛒 **Point of Sale (POS)** — Process transactions with FIFO inventory deduction
- 📦 **Product Management** — Add, update, restock, and delete vegetable items with images
- 📋 **Transactions** — View transaction history and individual transaction details
- 📈 **Analytics** — Sales trends, top sellers, and revenue breakdown
- 📑 **Reports** — Export sales data to CSV
- 👥 **Accounts** — Multi-user support with role management (Owner/Staff)
- 🔐 **Security** — CSRF protection, brute-force login lockout, session management

---

## 🛠️ Tech Stack
| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite (via `database.py`) |
| Frontend | HTML, CSS, Jinja2 templates |
| Data | Pandas, OpenPyXL |
| Auth | Werkzeug password hashing |

---

## ⚙️ Setup
**Requirements:** Python 3.8 or higher

1. Clone the repository:
```bash
   git clone https://github.com/kvzl0/Ajon-Veggies.git
   cd Ajon-Veggies
```
2. Install dependencies:
```bash
   pip install -r requirements.txt
```
3. Run the app:
```bash
   python app.py
```
4. Open your browser and go to:
```
   http://localhost:5000
```

---

## 🔑 Default Login
| Field | Value |
|---|---|
| Username | `admin` |
| Password | `admin123` |

> ⚠️ Change your password after first login.

---

## 📂 Project Structure

```
quirol_v6/
├── app.py                                  # Main Flask application & routes
├── database.py                             # DB initialization, FIFO logic, data import
├── requirements.txt                        # Python dependencies
├── quirol.db                               # SQLite database (auto-created on first run)
├── data/
│   ├── quirol_veggies_monthly_sales.xlsx   # Historical sales data
│   └── daily_sales.csv
├── templates/                              # Jinja2 HTML templates
│   ├── dashboard.html
│   ├── pos.html
│   ├── products.html
│   ├── analytics.html
│   ├── reports.html
│   ├── accounts.html
│   └── ...
└── static/
    └── img/products/                       # Vegetable product images
```

---

## 📝 Notes
- The database (`quirol.db`) is created automatically on first run
- Historical Excel sales data is imported automatically on first run
- All data is stored locally — no external database needed
- The project is fully portable — just zip and share

---

## 👨‍💻 Developer
**Kiev Gonzales** — Business Intelligence System Project