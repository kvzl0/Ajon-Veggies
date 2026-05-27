# Quirol Veggies — Data-Driven Vegetable Distributor POS with Analytics

## Requirements
- Python 3.8 or higher
- pip

## Setup (first time only)

1. Open a terminal inside the `quirol_veggies` folder.
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running the System

```
python app.py
```

Then open your browser and go to:
```
http://localhost:5000
```

## Default Login
- Username: `admin`
- Password: `admin123`

> Change your password after first login by registering a new account.

## Notes
- The database file `quirol.db` is created automatically on first run.
- The 3-month Excel sales data is imported automatically on first run.
- The entire project is portable — just zip the folder and share it.
- All data is stored locally in `quirol.db` (SQLite).
