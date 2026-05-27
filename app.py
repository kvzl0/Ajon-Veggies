from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db, init_db, import_excel_data, import_csv_data, seed_admin, fifo_deduct
from datetime import datetime, timedelta
from functools import wraps
import random, string, os, secrets, time, re, csv, io

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)

EXCEL_PATH = os.path.join(os.path.dirname(__file__), 'data', 'quirol_veggies_monthly_sales.xlsx')

# ── Brute-force protection ────────────────────────────────────────────────────
login_attempts = {}
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 300

def get_ip():
    return request.remote_addr or '0.0.0.0'

def is_locked(ip):
    entry = login_attempts.get(ip)
    if not entry: return False
    if entry['count'] >= MAX_ATTEMPTS:
        if time.time() < entry['locked_until']: return True
        else: login_attempts.pop(ip, None)
    return False

def record_failed(ip):
    entry = login_attempts.get(ip, {'count': 0, 'locked_until': 0})
    entry['count'] += 1
    if entry['count'] >= MAX_ATTEMPTS:
        entry['locked_until'] = time.time() + LOCKOUT_SECONDS
    login_attempts[ip] = entry

def reset_attempts(ip):
    login_attempts.pop(ip, None)

# ── CSRF ──────────────────────────────────────────────────────────────────────
def generate_csrf():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(32)
    return session['_csrf']

def validate_csrf():
    token = request.form.get('_csrf') or request.headers.get('X-CSRF-Token')
    return token and token == session.get('_csrf')

app.jinja_env.globals['csrf_token'] = generate_csrf

def sanitize_str(value, max_len=100):
    if not value: return ''
    return str(value).strip()[:max_len]

def validate_username(u):
    return bool(u) and 3 <= len(u) <= 50 and re.match(r'^[a-zA-Z0-9_]+$', u)

def validate_positive_float(v):
    try: return float(v) >= 0
    except: return False


ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        last_active = session.get('last_active')
        if last_active and datetime.now().timestamp() - last_active > 28800:
            session.clear()
            flash('Session expired. Please log in again.')
            return redirect(url_for('login'))
        session['last_active'] = datetime.now().timestamp()
        session.permanent = True
        return f(*args, **kwargs)
    return decorated


def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'owner':
            flash('Access denied. Owner privileges required.')
            return redirect(url_for('pos'))
        return f(*args, **kwargs)
    return decorated

def csrf_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method == 'POST' and not validate_csrf():
            flash('Invalid request. Please try again.')
            return redirect(request.referrer or url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def generate_transaction_code():
    return 'TXN-' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard') if 'user_id' in session else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not validate_csrf():
            flash('Invalid request. Please try again.')
            return render_template('login.html')
        ip = get_ip()
        if is_locked(ip):
            remaining = int(login_attempts[ip]['locked_until'] - time.time())
            flash(f'Too many failed attempts. Try again in {remaining} seconds.')
            return render_template('login.html')
        username = sanitize_str(request.form.get('username', ''))
        password = request.form.get('password', '')
        if not username or not password:
            flash('Please enter both username and password.')
            return render_template('login.html')
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            reset_attempts(ip)
            session.clear()
            session.update({'user_id': user['id'], 'username': user['username'], 'role': user['role'], 'last_active': datetime.now().timestamp()})
            session.permanent = True
            return redirect(url_for('dashboard') if user['role'] == 'owner' else url_for('pos'))
        else:
            record_failed(ip)
            left = MAX_ATTEMPTS - login_attempts.get(ip, {}).get('count', 0)
            flash(f'Invalid username or password. {max(0,left)} attempt(s) remaining.' if left > 0 else 'Account locked for 5 minutes.')
    return render_template('login.html')

@app.route('/accounts')
@login_required
@owner_required
def accounts():
    conn = get_db()
    users = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY created_at').fetchall()
    conn.close()
    return render_template('accounts.html', users=users)

@app.route('/accounts/create', methods=['POST'])
@login_required
@owner_required
@csrf_required
def create_account():
    username = sanitize_str(request.form.get('username', ''))
    password = request.form.get('password', '')
    confirm  = request.form.get('confirm', '')
    role     = request.form.get('role', 'cashier')
    if role not in ('owner', 'cashier'):
        role = 'cashier'
    if not validate_username(username):
        flash('Username must be 3–50 characters, letters/numbers/underscore only.')
    elif len(password) < 6:
        flash('Password must be at least 6 characters.')
    elif password != confirm:
        flash('Passwords do not match.')
    else:
        try:
            conn = get_db()
            conn.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                         (username, generate_password_hash(password), role))
            conn.commit(); conn.close()
            flash(f'Account "{username}" created as {role.title()}.')
        except Exception:
            flash('Username already taken.')
    return redirect(url_for('accounts'))

@app.route('/accounts/role/<int:uid>', methods=['POST'])
@login_required
@owner_required
@csrf_required
def change_role(uid):
    if uid == session['user_id']:
        flash('You cannot change your own role.')
        return redirect(url_for('accounts'))
    new_role = request.form.get('role', 'cashier')
    if new_role not in ('owner', 'cashier'):
        new_role = 'cashier'
    conn = get_db()
    conn.execute('UPDATE users SET role=? WHERE id=?', (new_role, uid))
    conn.commit(); conn.close()
    flash('Role updated.')
    return redirect(url_for('accounts'))

@app.route('/accounts/delete/<int:uid>', methods=['POST'])
@login_required
@owner_required
@csrf_required
def delete_account(uid):
    if uid == session['user_id']:
        flash('You cannot delete your own account.')
        return redirect(url_for('accounts'))
    conn = get_db()
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit(); conn.close()
    flash('Account deleted.')
    return redirect(url_for('accounts'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_required
@owner_required
def dashboard():
    conn = get_db()
    hist = conn.execute('SELECT month, SUM(monthly_sales) as total FROM historical_sales GROUP BY month ORDER BY id').fetchall()

    # Real daily sales trend from all historical transactions
    daily_trend = conn.execute('''
        SELECT date(created_at) as day, SUM(total_amount) as total
        FROM transactions
        GROUP BY day ORDER BY day
    ''').fetchall()
    best = conn.execute('''SELECT p.name, SUM(hs.monthly_sales) as hist_sales, SUM(hs.monthly_qty) as hist_qty
        FROM historical_sales hs JOIN products p ON p.id=hs.product_id GROUP BY p.id ORDER BY hist_sales DESC LIMIT 5''').fetchall()
    slow = conn.execute('''SELECT p.name, AVG(hs.days_sold) as avg_days, SUM(hs.monthly_sales) as total_sales
        FROM historical_sales hs JOIN products p ON p.id=hs.product_id GROUP BY p.id ORDER BY avg_days ASC LIMIT 5''').fetchall()
    low_stock = conn.execute('SELECT name,stock_kg,low_stock_threshold FROM products WHERE stock_kg<=low_stock_threshold ORDER BY stock_kg').fetchall()

    # Spoilage alerts — batches expiring within 2 days or already expired
    spoilage = conn.execute('''
        SELECT p.name, sb.remaining_kg, sb.expires_at,
               CAST((julianday(sb.expires_at) - julianday('now')) AS INTEGER) as days_left
        FROM stock_batches sb JOIN products p ON p.id=sb.product_id
        WHERE sb.remaining_kg > 0 AND sb.expires_at <= datetime('now', '+2 days')
        ORDER BY sb.expires_at ASC
    ''').fetchall()

    recs_raw = conn.execute('''SELECT p.name, p.unit_price, AVG(hs.monthly_sales) as avg_sales,
        AVG(hs.days_sold) as avg_days, p.stock_kg
        FROM historical_sales hs JOIN products p ON p.id=hs.product_id GROUP BY p.id''').fetchall()

    today      = conn.execute("SELECT COALESCE(SUM(total_amount),0) as total, COUNT(*) as count FROM transactions WHERE date(created_at)=date('now')").fetchone()
    total_rev  = conn.execute("SELECT COALESCE(SUM(total_amount),0) as t FROM transactions").fetchone()
    hist_total = conn.execute("SELECT COALESCE(SUM(monthly_sales),0) as t FROM historical_sales").fetchone()
    conn.close()

    recommendations = []
    for r in recs_raw:
        avg_sales, avg_days, stock = r['avg_sales'] or 0, r['avg_days'] or 0, r['stock_kg'] or 0
        price = r['unit_price'] or 0
        # Restock recommendation
        if avg_sales > 30000 and stock < 100:
            recommendations.append({'name': r['name'], 'type': 'restock', 'msg': f"Top seller with low stock ({stock:.0f} kg). Consider restocking."})
        # Slow mover — suggest price reduction
        elif avg_days < 6:
            suggested = round(price * 0.90, 2)
            recommendations.append({'name': r['name'], 'type': 'slow', 'msg': f"Averaging only {avg_days:.1f} days sold/month. Consider reducing price to ₱{suggested:.2f}/kg to move stock faster."})

    return render_template('dashboard.html',
        hist_months=[r['month'] for r in hist], hist_totals=[r['total'] for r in hist],
        best_sellers=best, slow_movers=slow, low_stock=low_stock,
        recommendations=recommendations, spoilage_alerts=spoilage,
        today_sales=today['total'], today_count=today['count'],
        total_revenue=total_rev['t'] + hist_total['t'],
        daily_labels=[r['day'] for r in daily_trend],
        daily_totals=[r['total'] for r in daily_trend])

# ── POS ───────────────────────────────────────────────────────────────────────
@app.route('/pos')
@login_required
def pos():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return render_template('pos.html', products=products)

@app.route('/api/checkout', methods=['POST'])
@login_required
def checkout():
    if not validate_csrf():
        return jsonify({'error': 'Invalid request.'}), 403
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid data.'}), 400
    items = data.get('items', [])
    if not items or not isinstance(items, list):
        return jsonify({'error': 'No items in order.'}), 400
    conn = get_db()
    try:
        total, validated = 0, []
        for item in items:
            pid = int(item.get('product_id', 0))
            qty = float(item.get('quantity_kg', 0))
            if pid <= 0 or qty <= 0:
                conn.close(); return jsonify({'error': 'Invalid item data.'}), 400
            product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
            if not product:
                conn.close(); return jsonify({'error': 'Product not found.'}), 400
            subtotal = round(qty * product['unit_price'], 2)
            total += subtotal
            validated.append({'product_id': pid, 'quantity_kg': qty, 'unit_price': product['unit_price'], 'subtotal': subtotal})

        code   = generate_transaction_code()
        cursor = conn.execute("INSERT INTO transactions (transaction_code,total_amount,created_by) VALUES (?,?,?)",
                              (code, round(total,2), session['user_id']))
        txn_id = cursor.lastrowid

        for item in validated:
            conn.execute("INSERT INTO transaction_items (transaction_id,product_id,quantity_kg,unit_price,subtotal) VALUES (?,?,?,?,?)",
                         (txn_id, item['product_id'], item['quantity_kg'], item['unit_price'], item['subtotal']))
            # FIFO deduction from batches
            fifo_deduct(conn, item['product_id'], item['quantity_kg'])
            # Update total stock
            conn.execute("UPDATE products SET stock_kg=MAX(0,stock_kg-?) WHERE id=?",
                         (item['quantity_kg'], item['product_id']))

        conn.commit(); conn.close()
        return jsonify({'success': True, 'code': code, 'total': round(total,2)})
    except (ValueError, TypeError):
        conn.close(); return jsonify({'error': 'Invalid data format.'}), 400
    except Exception:
        conn.close(); return jsonify({'error': 'Transaction failed. Please try again.'}), 500

# ── Transactions ──────────────────────────────────────────────────────────────
@app.route('/transactions')
@login_required
def transactions():
    conn = get_db()
    txns = conn.execute('''SELECT t.*, u.username FROM transactions t JOIN users u ON u.id=t.created_by
        ORDER BY t.created_at DESC LIMIT 100''').fetchall()
    conn.close()
    return render_template('transactions.html', transactions=txns)

@app.route('/transactions/<int:txn_id>')
@login_required
def transaction_detail(txn_id):
    conn = get_db()
    txn = conn.execute("SELECT * FROM transactions WHERE id=?", (txn_id,)).fetchone()
    if not txn:
        conn.close(); flash('Transaction not found.'); return redirect(url_for('transactions'))
    items = conn.execute('''SELECT ti.*, p.name FROM transaction_items ti JOIN products p ON p.id=ti.product_id
        WHERE ti.transaction_id=?''', (txn_id,)).fetchall()
    conn.close()
    return render_template('transaction_detail.html', txn=txn, items=items)

# ── Products ──────────────────────────────────────────────────────────────────
@app.route('/products')
@login_required
@owner_required
def products():
    conn = get_db()
    prods = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return render_template('products.html', products=prods)


@app.route('/products/add', methods=['POST'])
@login_required
@csrf_required
def add_product():
    name      = sanitize_str(request.form.get('name', ''))
    price     = request.form.get('unit_price', '')
    stock     = request.form.get('stock_kg', '0')
    threshold = request.form.get('low_stock_threshold', '50')
    shelf     = request.form.get('shelf_life_days', '7')
    if not name:
        flash('Product name is required.')
        return redirect(url_for('products'))
    if not all([validate_positive_float(price), validate_positive_float(stock), validate_positive_float(threshold)]):
        flash('Invalid values. Please enter valid positive numbers.')
        return redirect(url_for('products'))
    try:
        shelf_int = max(1, int(shelf))
    except Exception:
        shelf_int = 7
    try:
        conn = get_db()
        conn.execute(
            'INSERT INTO products (name, unit_price, stock_kg, low_stock_threshold, shelf_life_days) VALUES (?,?,?,?,?)',
            (name, float(price), float(stock), float(threshold), shelf_int)
        )
        conn.commit()
        conn.close()

        # Save image if provided
        image = request.files.get('image')
        if image and image.filename and allowed_file(image.filename):
            ext = image.filename.rsplit('.', 1)[1].lower()
            safe_name = name.replace(' ', '_')
            img_dir = os.path.join(app.root_path, 'static', 'img', 'products')
            image.save(os.path.join(img_dir, f'{safe_name}.{ext}'))

        flash(f'{name} added successfully.')
    except Exception:
        flash('A product with that name already exists.')
    return redirect(url_for('products'))

@app.route('/products/update/<int:pid>', methods=['POST'])
@login_required
@csrf_required
def update_product(pid):
    price     = request.form.get('unit_price','')
    stock     = request.form.get('stock_kg','')
    threshold = request.form.get('low_stock_threshold','')
    shelf     = request.form.get('shelf_life_days','7')
    if not all([validate_positive_float(price), validate_positive_float(stock), validate_positive_float(threshold)]):
        flash('Invalid values. Please enter valid positive numbers.')
        return redirect(url_for('products'))
    try:
        shelf_int = max(1, int(shelf))
    except Exception:
        shelf_int = 7
    conn = get_db()
    conn.execute("UPDATE products SET unit_price=?,stock_kg=?,low_stock_threshold=?,shelf_life_days=? WHERE id=?",
                 (float(price), float(stock), float(threshold), shelf_int, pid))
    conn.commit()
    conn.close()
    flash('Product updated successfully.')
    return redirect(url_for('products'))


@app.route('/products/delete/<int:pid>', methods=['POST'])
@login_required
@csrf_required
def delete_product(pid):
    conn = get_db()
    product = conn.execute('SELECT * FROM products WHERE id=?', (pid,)).fetchone()
    if not product:
        conn.close()
        flash('Product not found.')
        return redirect(url_for('products'))

    # Check if product has transaction history
    txn_count = conn.execute(
        'SELECT COUNT(*) FROM transaction_items WHERE product_id=?', (pid,)
    ).fetchone()[0]

    if txn_count > 0:
        conn.close()
        flash(f'Cannot delete {product["name"]} — it has {txn_count} transaction record(s). Consider setting stock to 0 instead.')
        return redirect(url_for('products'))

    # Delete stock batches and product
    conn.execute('DELETE FROM stock_batches WHERE product_id=?', (pid,))
    conn.execute('DELETE FROM products WHERE id=?', (pid,))
    conn.commit()
    conn.close()

    # Remove image if exists
    safe_name = product['name'].replace(' ', '_')
    img_dir = os.path.join(app.root_path, 'static', 'img', 'products')
    for ext in ['jpg', 'jpeg', 'png', 'webp']:
        img_path = os.path.join(img_dir, f'{safe_name}.{ext}')
        if os.path.exists(img_path):
            os.remove(img_path)
            break

    flash(f'{product["name"]} deleted successfully.')
    return redirect(url_for('products'))

# ── Stock Batches (FIFO restock) ──────────────────────────────────────────────
@app.route('/products/restock/<int:pid>', methods=['POST'])
@login_required
@csrf_required
def restock_product(pid):
    qty = request.form.get('qty_kg','')
    if not validate_positive_float(qty) or float(qty) <= 0:
        flash('Invalid quantity.')
        return redirect(url_for('products'))
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone()
    if not product:
        conn.close(); flash('Product not found.'); return redirect(url_for('products'))
    qty_f = float(qty)
    expires = datetime.now() + timedelta(days=product['shelf_life_days'])
    conn.execute("INSERT INTO stock_batches (product_id, quantity_kg, remaining_kg, expires_at) VALUES (?,?,?,?)",
                 (pid, qty_f, qty_f, expires.strftime('%Y-%m-%d %H:%M:%S')))
    conn.execute("UPDATE products SET stock_kg=stock_kg+? WHERE id=?", (qty_f, pid))
    conn.commit(); conn.close()
    flash(f'Restocked {qty_f:.1f} kg of {product["name"]}. Expires {expires.strftime("%b %d, %Y")}.')
    return redirect(url_for('products'))

# ── Analytics ─────────────────────────────────────────────────────────────────
@app.route('/analytics')
@login_required
@owner_required
def analytics():
    conn = get_db()
    months_order = ['December 2025', 'January 2026', 'February 2026']
    month_ranges = {
        'December 2025': ('2025-12-01', '2025-12-31'),
        'January 2026':  ('2026-01-01', '2026-01-31'),
        'February 2026': ('2026-02-01', '2026-02-28'),
    }

    products_map = {}
    for month, (start, end) in month_ranges.items():
        rows = conn.execute('''
            SELECT p.name,
                   SUM(ti.subtotal) as monthly_sales,
                   SUM(ti.quantity_kg) as monthly_qty,
                   COUNT(DISTINCT date(t.created_at)) as days_sold
            FROM transaction_items ti
            JOIN transactions t ON t.id = ti.transaction_id
            JOIN products p ON p.id = ti.product_id
            WHERE date(t.created_at) BETWEEN ? AND ?
            GROUP BY p.id ORDER BY p.name
        ''', (start, end)).fetchall()

        for r in rows:
            if r['name'] not in products_map:
                products_map[r['name']] = {m: {'sales':0,'qty':0,'days':0} for m in months_order}
            products_map[r['name']][month] = {
                'sales': r['monthly_sales'] or 0,
                'qty':   r['monthly_qty'] or 0,
                'days':  r['days_sold'] or 0,
            }

    # Fill any missing products with zeros
    all_products = conn.execute('SELECT name FROM products ORDER BY name').fetchall()
    for p in all_products:
        if p['name'] not in products_map:
            products_map[p['name']] = {m: {'sales':0,'qty':0,'days':0} for m in months_order}

    conn.close()
    return render_template('analytics.html', products_map=products_map, months=months_order)

# ── Financial Report ──────────────────────────────────────────────────────────
@app.route('/reports')
@login_required
@owner_required
def reports():
    conn = get_db()
    # Monthly summary from live transactions
    monthly = conn.execute('''
        SELECT strftime('%Y-%m', created_at) as month,
               COUNT(*) as txn_count,
               SUM(total_amount) as revenue
        FROM transactions GROUP BY month ORDER BY month DESC
    ''').fetchall()

    # Per-product sales from live transactions
    by_product = conn.execute('''
        SELECT p.name, SUM(ti.quantity_kg) as total_qty, SUM(ti.subtotal) as total_revenue,
               COUNT(DISTINCT ti.transaction_id) as txn_count
        FROM transaction_items ti JOIN products p ON p.id=ti.product_id
        GROUP BY p.id ORDER BY total_revenue DESC
    ''').fetchall()

    # Historical monthly totals
    hist = conn.execute('''
        SELECT month, SUM(monthly_sales) as revenue, SUM(monthly_qty) as qty
        FROM historical_sales GROUP BY month ORDER BY id
    ''').fetchall()

    # Grand totals
    live_total = conn.execute("SELECT COALESCE(SUM(total_amount),0) as t FROM transactions").fetchone()
    hist_total = conn.execute("SELECT COALESCE(SUM(monthly_sales),0) as t FROM historical_sales").fetchone()

    conn.close()
    return render_template('reports.html',
        monthly=monthly, by_product=by_product, hist=hist,
        live_total=live_total['t'], hist_total=hist_total['t'],
        grand_total=live_total['t'] + hist_total['t'])

@app.route('/reports/export')
@login_required
@owner_required
def export_report():
    date_from = request.args.get('date_from', '').strip()
    date_to   = request.args.get('date_to', '').strip()
    scope     = request.args.get('scope', 'all')  # 'all' or 'range'

    conn = get_db()

    # Build date filter
    if scope == 'range' and date_from and date_to:
        where  = "WHERE date(t.created_at) BETWEEN ? AND ?"
        params = (date_from, date_to)
        label  = f"{date_from}_to_{date_to}"
    else:
        where  = ""
        params = ()
        label  = "all"

    # Get per-product aggregated data matching the Excel format
    query = f"""
        SELECT
            p.name as item,
            p.unit_price,
            COUNT(DISTINCT date(t.created_at)) as days_sold,
            SUM(ti.quantity_kg) as monthly_qty,
            SUM(ti.subtotal) as monthly_sales
        FROM transaction_items ti
        JOIN transactions t ON t.id = ti.transaction_id
        JOIN products p ON p.id = ti.product_id
        {where}
        GROUP BY p.id
        ORDER BY p.name
    """
    rows = conn.execute(query, params).fetchall() if params else conn.execute(query).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header matching Excel format
    writer.writerow(['Item', 'Unit Price (₱)', 'Days Sold', 'Daily Avg Qty (kg)', 'Daily Avg Sales (₱)', 'Monthly Qty (kg)', 'Monthly Sales (₱)'])

    total_days = 0
    total_daily_avg_qty = 0
    total_daily_avg_sales = 0
    total_qty = 0
    total_sales = 0
    total_price = 0

    for r in rows:
        days   = r['days_sold'] or 1
        qty    = r['monthly_qty'] or 0
        sales  = r['monthly_sales'] or 0
        d_qty  = round(qty / days, 1)
        d_sales = round(sales / days, 2)

        writer.writerow([
            r['item'],
            r['unit_price'],
            days,
            d_qty,
            d_sales,
            round(qty, 1),
            round(sales, 2)
        ])

        total_price      += r['unit_price']
        total_days       += days
        total_daily_avg_qty   += d_qty
        total_daily_avg_sales += d_sales
        total_qty        += qty
        total_sales      += sales

    # TOTAL row matching Excel format
    writer.writerow([
        'TOTAL',
        round(total_price, 2),
        total_days,
        round(total_daily_avg_qty, 1),
        round(total_daily_avg_sales, 2),
        round(total_qty, 1),
        round(total_sales, 2)
    ])

    filename = f"quirol_veggies_sales_{label}.csv"
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    return response


# ── Change Password ───────────────────────────────────────────────────────────
@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    if not validate_csrf():
        return jsonify({'error': 'Invalid request.'}), 403
    current  = request.json.get('current', '')
    new_pw   = request.json.get('new_pw', '')
    confirm  = request.json.get('confirm', '')
    if not current or not new_pw or not confirm:
        return jsonify({'error': 'All fields are required.'}), 400
    if new_pw != confirm:
        return jsonify({'error': 'New passwords do not match.'}), 400
    if len(new_pw) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if not user or not check_password_hash(user['password'], current):
        conn.close()
        return jsonify({'error': 'Current password is incorrect.'}), 400
    conn.execute('UPDATE users SET password=? WHERE id=?',
                 (generate_password_hash(new_pw), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

# ── Product image serving ─────────────────────────────────────────────────────
@app.route('/product-image/<product_name>')
def product_image(product_name):
    from flask import send_from_directory
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', product_name.replace(' ', '_'))
    img_dir = os.path.join(app.root_path, 'static', 'img', 'products')
    for ext in ['jpg', 'jpeg', 'png', 'webp']:
        filename = f"{safe_name}.{ext}"
        if os.path.exists(os.path.join(img_dir, filename)):
            return send_from_directory(img_dir, filename)
    return send_from_directory(img_dir, 'placeholder.svg')

# ── Error handlers ────────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message='Page not found.'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500, message='Something went wrong. Please try again.'), 500

@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message='Access denied.'), 403

if __name__ == '__main__':
    CSV_PATH = os.path.join(os.path.dirname(__file__), 'data', 'daily_sales.csv')
    init_db()
    seed_admin()  # Must run before CSV import so admin user exists
    import_excel_data(EXCEL_PATH)
    if os.path.exists(CSV_PATH):
        import_csv_data(CSV_PATH)
    print("\n✅ Ajon Veggies system is running!")
    print("   Open http://localhost:5000 in your browser")
    print("   Default login: admin / admin123\n")
    app.run(debug=False, port=5000)
