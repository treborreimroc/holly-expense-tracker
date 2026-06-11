from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
import bcrypt
from datetime import datetime
from functools import wraps
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL not set")
    result = urlparse(database_url)
    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )
    return conn

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return redirect(url_for('login'))
    
@app.route('/inspiration')
@login_required
def inspiration():
    return render_template('inspiration.html')
    @app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', 'admin')
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('add_expense'))
        else:
            return render_template('login.html', error='Invalid password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ============= EXPENSES =============
@app.route('/add-expense', methods=['GET', 'POST'])
@login_required
def add_expense():
    if request.method == 'POST':
        date_val = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        amount = float(request.form['amount'])
        source_id = request.form['source_id']
        description = request.form.get('description', '')
        category_id = request.form['category_id']
        subcategory_id = request.form.get('subcategory_id') or None
        vendor_id = request.form.get('vendor_id') or None
        notes = request.form.get('notes', '')

        # Handle tax
        tax_rate_id = request.form.get('tax_rate_id') or None
        subtotal    = request.form.get('subtotal') or None
        tax_amount  = request.form.get('tax_amount') or None
        if subtotal: subtotal = float(subtotal)
        if tax_amount: tax_amount = float(tax_amount)

        # Handle receipt upload
        receipt_data = None
        receipt_mime = None
        if 'receipt' in request.files:
            file = request.files['receipt']
            if file and file.filename:
                receipt_data = psycopg2.Binary(file.read())
                receipt_mime = file.content_type or 'image/jpeg'

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO expenses (date, source_id, description, category_id,
                                subcategory_id, vendor_id, amount, notes,
                                tax_rate_id, subtotal, tax_amount,
                                receipt_data, receipt_mime_type, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (date_val, source_id, description, category_id, subcategory_id,
                vendor_id, amount, notes, tax_rate_id, subtotal, tax_amount,
                receipt_data, receipt_mime))
        conn.commit(); cursor.close(); conn.close()
        return redirect(url_for('view_expenses'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order, name'); tax_rates = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('add_expense.html', sources=sources, categories=categories,
                         subcategories=subcategories, vendors=vendors,
                         tax_rates=tax_rates,
                         today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/view-expenses')
@login_required
def view_expenses():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    filter_date_from = request.args.get('date_from', '')
    filter_date_to = request.args.get('date_to', '')
    filter_category = request.args.get('category_id', '')
    filter_subcategory = request.args.get('subcategory_id', '')
    filter_vendor = request.args.get('vendor_id', '')
    filter_source = request.args.get('source_id', '')
    filter_search = request.args.get('search', '')
    query = """
        SELECT e.*, s.name as source_name, c.name as category_name,
               c.color as category_color, sc.name as subcategory_name, v.name as vendor_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        WHERE (e.archived = %s) AND (e.is_split = 0 OR e.is_split = 2)
    """
    show_archived = request.args.get('show_archived') == 'true'
    params = [1 if show_archived else 0]
    if filter_date_from: query += ' AND e.date >= %s'; params.append(filter_date_from)
    if filter_date_to: query += ' AND e.date <= %s'; params.append(filter_date_to)
    if filter_category: query += ' AND e.category_id = %s'; params.append(filter_category)
    if filter_subcategory: query += ' AND e.subcategory_id = %s'; params.append(filter_subcategory)
    if filter_vendor: query += ' AND e.vendor_id = %s'; params.append(filter_vendor)
    if filter_source: query += ' AND e.source_id = %s'; params.append(filter_source)
    if filter_search:
        query += ' AND (e.description ILIKE %s OR e.notes ILIKE %s)'
        params.append(f'%{filter_search}%'); params.append(f'%{filter_search}%')
    query += ' ORDER BY e.date DESC, e.created_at DESC'
    cursor.execute(query, params)
    expenses = cursor.fetchall()
    total = sum(float(e['amount']) for e in expenses)

    # Check which expenses have receipts (safe — handles missing column)
    receipt_ids = set()
    try:
        if expenses:
            exp_ids = [e['id'] for e in expenses]
            placeholders = ','.join(['%s'] * len(exp_ids))
            cursor.execute(f'SELECT id FROM expenses WHERE id IN ({placeholders}) AND receipt_data IS NOT NULL', exp_ids)
            receipt_ids = {r['id'] for r in cursor.fetchall()}
    except Exception:
        pass  # Column doesn't exist yet — receipts just won't show
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.close(); conn.close()
    filters_active = any([filter_date_from, filter_date_to, filter_category,
                          filter_subcategory, filter_vendor, filter_source, filter_search])
    return render_template('view_expenses.html', expenses=expenses, total=total,
                         receipt_ids=receipt_ids,
                         show_archived=show_archived,
                         categories=categories, subcategories=subcategories,
                         vendors=vendors, sources=sources,
                         filter_date_from=filter_date_from, filter_date_to=filter_date_to,
                         filter_category=filter_category, filter_subcategory=filter_subcategory,
                         filter_vendor=filter_vendor, filter_source=filter_source,
                         filter_search=filter_search, filters_active=filters_active)

@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if request.method == 'POST':
        cursor.execute("""
            UPDATE expenses SET date=%s, source_id=%s, description=%s, category_id=%s,
                subcategory_id=%s, vendor_id=%s, amount=%s, notes=%s WHERE id=%s
        """, (request.form.get('date'), request.form['source_id'],
              request.form.get('description',''), request.form['category_id'],
              request.form.get('subcategory_id') or None, request.form.get('vendor_id') or None,
              float(request.form['amount']), request.form.get('notes',''), expense_id))
        conn.commit(); cursor.close(); conn.close()
        return redirect(url_for('view_expenses'))
    cursor.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,))
    expense = cursor.fetchone()
    if not expense: cursor.close(); conn.close(); return "Expense not found", 404
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('edit_expense.html', expense=expense, sources=sources,
                         categories=categories, subcategories=subcategories, vendors=vendors)

@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM expenses WHERE id = %s', (expense_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('view_expenses'))

# ============= INCOME =============
@app.route('/add-income', methods=['GET', 'POST'])
@login_required
def add_income():
    if request.method == 'POST':
        date_val = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        amount = float(request.form['amount'])
        source_id = request.form.get('source_id') or None
        description = request.form.get('description', '')
        category_id = request.form.get('category_id') or None
        notes = request.form.get('notes', '')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO income (date, source_id, description, category_id, amount, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (date_val, source_id, description, category_id, amount, notes))
        conn.commit(); cursor.close(); conn.close()
        return redirect(url_for('view_income'))
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM income_categories ORDER BY name'); income_categories = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('add_income.html', sources=sources, income_categories=income_categories,
                         today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/view-income')
@login_required
def view_income():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    filter_date_from = request.args.get('date_from', '')
    filter_date_to = request.args.get('date_to', '')
    filter_category = request.args.get('category_id', '')
    filter_source = request.args.get('source_id', '')
    filter_search = request.args.get('search', '')
    query = """
        SELECT i.*, s.name as source_name, ic.name as category_name, ic.color as category_color
        FROM income i
        LEFT JOIN sources s ON i.source_id = s.id
        LEFT JOIN income_categories ic ON i.category_id = ic.id
        WHERE (i.archived = %s)
    """
    show_archived = request.args.get('show_archived') == 'true'
    params = [1 if show_archived else 0]
    if filter_date_from: query += ' AND i.date >= %s'; params.append(filter_date_from)
    if filter_date_to: query += ' AND i.date <= %s'; params.append(filter_date_to)
    if filter_category: query += ' AND i.category_id = %s'; params.append(filter_category)
    if filter_source: query += ' AND i.source_id = %s'; params.append(filter_source)
    if filter_search:
        query += ' AND (i.description ILIKE %s OR i.notes ILIKE %s)'
        params.append(f'%{filter_search}%'); params.append(f'%{filter_search}%')
    query += ' ORDER BY i.date DESC, i.created_at DESC'
    cursor.execute(query, params)
    income_list = cursor.fetchall()
    total = sum(float(i['amount']) for i in income_list)
    cursor.execute('SELECT * FROM income_categories ORDER BY name'); income_categories = cursor.fetchall()
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.close(); conn.close()
    filters_active = any([filter_date_from, filter_date_to, filter_category, filter_source, filter_search])
    return render_template('view_income.html', income_list=income_list, total=total,
                         show_archived=show_archived,
                         income_categories=income_categories, sources=sources,
                         filter_date_from=filter_date_from, filter_date_to=filter_date_to,
                         filter_category=filter_category, filter_source=filter_source,
                         filter_search=filter_search, filters_active=filters_active)

@app.route('/income/edit/<int:income_id>', methods=['GET', 'POST'])
@login_required
def edit_income(income_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if request.method == 'POST':
        cursor.execute("""
            UPDATE income SET date=%s, source_id=%s, description=%s,
                category_id=%s, amount=%s, notes=%s WHERE id=%s
        """, (request.form.get('date'), request.form.get('source_id') or None,
              request.form.get('description',''), request.form.get('category_id') or None,
              float(request.form['amount']), request.form.get('notes',''), income_id))
        conn.commit(); cursor.close(); conn.close()
        return redirect(url_for('view_income'))
    cursor.execute('SELECT * FROM income WHERE id = %s', (income_id,))
    income = cursor.fetchone()
    if not income: cursor.close(); conn.close(); return "Income not found", 404
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM income_categories ORDER BY name'); income_categories = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('edit_income.html', income=income, sources=sources,
                         income_categories=income_categories)

@app.route('/income/delete/<int:income_id>', methods=['POST'])
@login_required
def delete_income(income_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM income WHERE id = %s', (income_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('view_income'))

# ============= BUDGET =============
@app.route('/budget')
@login_required
def budget():
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Month date range
    y, m = int(selected_month[:4]), int(selected_month[5:7])
    month_start = f'{y}-{m:02d}-01'
    month_end = f'{y+1}-01-01' if m == 12 else f'{y}-{m+1:02d}-01'

    # All categories
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()

    # All subcategories with their category
    cursor.execute("""
        SELECT sc.*, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    """)
    all_subcategories = cursor.fetchall()

    # Budgets for this month — category level
    cursor.execute('SELECT * FROM budget WHERE month = %s', (selected_month,))
    cat_budgets = {row['category_id']: float(row['amount']) for row in cursor.fetchall()}

    # Budgets for this month — subcategory level
    cursor.execute('SELECT * FROM budget_subcategory WHERE month = %s', (selected_month,))
    sub_budgets = {row['subcategory_id']: float(row['amount']) for row in cursor.fetchall()}

    # Actual spending by category
    cursor.execute("""
        SELECT category_id, SUM(amount) as total
        FROM expenses WHERE archived = 0 AND date >= %s AND date < %s
        GROUP BY category_id
    """, (month_start, month_end))
    cat_spending = {row['category_id']: float(row['total']) for row in cursor.fetchall()}

    # Actual spending by subcategory
    cursor.execute("""
        SELECT subcategory_id, SUM(amount) as total
        FROM expenses WHERE archived = 0 AND date >= %s AND date < %s
        AND subcategory_id IS NOT NULL
        GROUP BY subcategory_id
    """, (month_start, month_end))
    sub_spending = {row['subcategory_id']: float(row['total']) for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    # Build structured data: categories with nested subcategories
    budget_data = []
    total_budgeted = 0
    total_spent = 0

    for cat in categories:
        cat_id = cat['id']
        budgeted = cat_budgets.get(cat_id, 0)
        spent = cat_spending.get(cat_id, 0)
        remaining = budgeted - spent

        # Get subcategories for this category
        subs = []
        for sub in all_subcategories:
            if sub['category_id'] == cat_id:
                sub_budgeted = sub_budgets.get(sub['id'], 0)
                sub_spent = sub_spending.get(sub['id'], 0)
                subs.append({
                    'subcategory_id': sub['id'],
                    'subcategory_name': sub['name'],
                    'budgeted': sub_budgeted,
                    'spent': sub_spent,
                    'remaining': sub_budgeted - sub_spent
                })

        budget_data.append({
            'category_id': cat_id,
            'category_name': cat['name'],
            'color': cat['color'],
            'budgeted': budgeted,
            'spent': spent,
            'remaining': remaining,
            'subcategories': subs
        })
        total_budgeted += budgeted
        total_spent += spent

    return render_template('budget.html',
                         budget_data=budget_data,
                         selected_month=selected_month,
                         total_budgeted=total_budgeted,
                         total_spent=total_spent)

@app.route('/budget/set', methods=['POST'])
@login_required
def set_budget():
    month = request.form['month']
    conn = get_db_connection()
    cursor = conn.cursor()

    # Process all form fields
    for key, value in request.form.items():
        if key == 'month':
            continue
        amount = float(value) if value else 0

        if key.startswith('cat_'):
            category_id = int(key[4:])
            cursor.execute("""
                INSERT INTO budget (category_id, month, amount)
                VALUES (%s, %s, %s)
                ON CONFLICT (category_id, month) DO UPDATE SET amount = EXCLUDED.amount
            """, (category_id, month, amount))

        elif key.startswith('sub_'):
            subcategory_id = int(key[4:])
            cursor.execute("""
                INSERT INTO budget_subcategory (subcategory_id, month, amount)
                VALUES (%s, %s, %s)
                ON CONFLICT (subcategory_id, month) DO UPDATE SET amount = EXCLUDED.amount
            """, (subcategory_id, month, amount))

    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('budget', month=month))

@app.route('/budget/copy', methods=['POST'])
@login_required
def copy_budget():
    month = request.form['month']
    y, m = int(month[:4]), int(month[5:7])
    prev_month = f'{y-1}-12' if m == 1 else f'{y}-{m-1:02d}'

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Copy category budgets
    cursor.execute('SELECT * FROM budget WHERE month = %s', (prev_month,))
    for row in cursor.fetchall():
        cursor.execute("""
            INSERT INTO budget (category_id, month, amount)
            VALUES (%s, %s, %s)
            ON CONFLICT (category_id, month) DO UPDATE SET amount = EXCLUDED.amount
        """, (row['category_id'], month, row['amount']))

    # Copy subcategory budgets
    cursor.execute('SELECT * FROM budget_subcategory WHERE month = %s', (prev_month,))
    for row in cursor.fetchall():
        cursor.execute("""
            INSERT INTO budget_subcategory (subcategory_id, month, amount)
            VALUES (%s, %s, %s)
            ON CONFLICT (subcategory_id, month) DO UPDATE SET amount = EXCLUDED.amount
        """, (row['subcategory_id'], month, row['amount']))

    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('budget', month=month))

# ============= MANAGE =============
@app.route('/manage')
@login_required
def manage():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT COUNT(*) as count FROM sources'); sources_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM categories'); categories_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM subcategories'); subcategories_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM vendors'); vendors_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM expenses'); expenses_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM income'); income_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM income_categories'); income_cat_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM users'); users_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM tax_rates WHERE is_active = 1'); tax_rates_count = cursor.fetchone()['count']
    cursor.close(); conn.close()
    stats = {'sources': sources_count, 'categories': categories_count, 'subcategories': subcategories_count, 'vendors': vendors_count,
             'expenses': expenses_count, 'income': income_count, 'income_categories': income_cat_count,
             'users': users_count, 'tax_rates': tax_rates_count}
    return render_template('manage.html', stats=stats)

@app.route('/manage/sources')
@login_required
def manage_sources():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_sources.html', sources=sources)

@app.route('/manage/sources/add', methods=['POST'])
@login_required
def add_source():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO sources (name, type) VALUES (%s, %s)',
                  (request.form['name'], request.form.get('type', '')))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_sources'))

@app.route('/manage/sources/delete/<int:source_id>', methods=['POST'])
@login_required
def delete_source(source_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM sources WHERE id = %s', (source_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_sources'))

@app.route('/manage/categories')
@login_required
def manage_categories():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_categories.html', categories=categories)

@app.route('/manage/categories/add', methods=['POST'])
@login_required
def add_category():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO categories (name, color) VALUES (%s, %s)',
                  (request.form['name'], request.form.get('color', '#6c757d')))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_categories'))

@app.route('/manage/categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    conn = get_db_connection(); cursor = conn.cursor()
    # Nullify foreign keys first, then delete subcategories, then category
    cursor.execute('UPDATE expenses SET subcategory_id = NULL WHERE subcategory_id IN (SELECT id FROM subcategories WHERE category_id = %s)', (category_id,))
    cursor.execute('UPDATE expenses SET category_id = NULL WHERE category_id = %s', (category_id,))
    cursor.execute('DELETE FROM budget WHERE category_id = %s', (category_id,))
    cursor.execute('DELETE FROM budget_subcategory WHERE subcategory_id IN (SELECT id FROM subcategories WHERE category_id = %s)', (category_id,))
    cursor.execute('DELETE FROM subcategories WHERE category_id = %s', (category_id,))
    cursor.execute('DELETE FROM categories WHERE id = %s', (category_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_categories'))

@app.route('/manage/vendors')
@login_required
def manage_vendors():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_vendors.html', vendors=vendors)

@app.route('/manage/vendors/add', methods=['POST'])
@login_required
def add_vendor():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO vendors (name) VALUES (%s)', (request.form['name'],))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_vendors'))

@app.route('/manage/vendors/delete/<int:vendor_id>', methods=['POST'])
@login_required
def delete_vendor(vendor_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM vendors WHERE id = %s', (vendor_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_vendors'))

@app.route('/manage/subcategories')
@login_required
def manage_subcategories():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT s.*, c.name as category_name FROM subcategories s
        LEFT JOIN categories c ON s.category_id = c.id ORDER BY c.name, s.name
    """); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_subcategories.html', subcategories=subcategories, categories=categories)

@app.route('/manage/subcategories/add', methods=['POST'])
@login_required
def add_subcategory():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO subcategories (name, category_id) VALUES (%s, %s)',
                  (request.form['name'], request.form['category_id']))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_subcategories'))

@app.route('/manage/subcategories/delete/<int:subcategory_id>', methods=['POST'])
@login_required
def delete_subcategory(subcategory_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM subcategories WHERE id = %s', (subcategory_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_subcategories'))

@app.route('/manage/income-categories')
@login_required
def manage_income_categories():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM income_categories ORDER BY name'); income_categories = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_income_categories.html', income_categories=income_categories)

@app.route('/manage/income-categories/add', methods=['POST'])
@login_required
def add_income_category():
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('INSERT INTO income_categories (name, color) VALUES (%s, %s)',
                  (request.form['name'], request.form.get('color', '#28a745')))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_income_categories'))

@app.route('/manage/income-categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_income_category(category_id):
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('DELETE FROM income_categories WHERE id = %s', (category_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_income_categories'))

# ============= QUICK ADD =============
@app.route('/quick-add/source', methods=['POST'])
@login_required
def quick_add_source():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO sources (name, type) VALUES (%s, %s) RETURNING id', (name, 'Bank Account'))
        new_id = cursor.fetchone()[0]; conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/category', methods=['POST'])
@login_required
def quick_add_category():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO categories (name, color) VALUES (%s, %s) RETURNING id', (name, '#6c757d'))
        new_id = cursor.fetchone()[0]; conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/vendor', methods=['POST'])
@login_required
def quick_add_vendor():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO vendors (name) VALUES (%s) RETURNING id', (name,))
        new_id = cursor.fetchone()[0]; conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/subcategory', methods=['POST'])
@login_required
def quick_add_subcategory():
    name = request.form.get('name', '').strip()
    category_id = request.form.get('category_id')
    if name and category_id:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO subcategories (name, category_id) VALUES (%s, %s) RETURNING id',
                      (name, category_id))
        new_id = cursor.fetchone()[0]; conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/income-category', methods=['POST'])
@login_required
def quick_add_income_category():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('INSERT INTO income_categories (name, color) VALUES (%s, %s) RETURNING id',
                      (name, '#28a745'))
        new_id = cursor.fetchone()[0]; conn.commit(); cursor.close(); conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})


# ============= P&L REPORT =============
@app.route('/pnl')
@login_required
def pnl():
    view_type = request.args.get('view_type', 'month')
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    selected_year = int(request.args.get('year', datetime.now().year))
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Determine date range for current period
    if view_type == 'month':
        y, m = int(selected_month[:4]), int(selected_month[5:7])
        start_date = f'{y}-{m:02d}-01'
        end_date = f'{y+1}-01-01' if m == 12 else f'{y}-{m+1:02d}-01'
        period_label = selected_month
        # Last year same month
        ly_start = f'{y-1}-{m:02d}-01'
        ly_end = f'{y}-{m:02d}-01' if m == 12 else f'{y-1}-{m+1:02d}-01' if m < 12 else f'{y}-01-01'
        ly_end = f'{y-1+1}-01-01' if m == 12 else f'{y-1}-{m+1:02d}-01'
    elif view_type == 'year':
        start_date = f'{selected_year}-01-01'
        end_date = f'{selected_year+1}-01-01'
        period_label = str(selected_year)
        ly_start = f'{selected_year-1}-01-01'
        ly_end = f'{selected_year}-01-01'
    else:  # range
        start_date = date_from
        end_date = date_to
        period_label = f'{date_from} to {date_to}'
        ly_start = ''
        ly_end = ''

    # ---- INCOME ----
    cursor.execute("""
        SELECT ic.name as category_name, ic.color, SUM(i.amount) as actual
        FROM income i
        LEFT JOIN income_categories ic ON i.category_id = ic.id
        WHERE i.archived = 0 AND i.date >= %s AND i.date < %s
        GROUP BY ic.name, ic.color ORDER BY actual DESC
    """, (start_date, end_date))
    income_rows = cursor.fetchall()

    # Income budgets for period (use month budget if month view)
    income_budget_dict = {}
    if view_type == 'month':
        cursor.execute("""
            SELECT ic.name as category_name, ib.amount
            FROM income_budget ib
            JOIN income_categories ic ON ib.category_id = ic.id
            WHERE ib.month = %s
        """, (selected_month,))
        for row in cursor.fetchall():
            income_budget_dict[row['category_name']] = float(row['amount'])

    # Last year income
    ly_income_dict = {}
    if ly_start and ly_end:
        cursor.execute("""
            SELECT ic.name as category_name, SUM(i.amount) as total
            FROM income i
            LEFT JOIN income_categories ic ON i.category_id = ic.id
            WHERE i.archived = 0 AND i.date >= %s AND i.date < %s
            GROUP BY ic.name
        """, (ly_start, ly_end))
        for row in cursor.fetchall():
            ly_income_dict[row['category_name']] = float(row['total'])

    income_by_category = []
    total_income = 0
    total_income_budget = 0
    for row in income_rows:
        cat_name = row['category_name'] or 'Uncategorized'
        actual = float(row['actual'])
        budget = income_budget_dict.get(cat_name, 0)
        ly_amount = ly_income_dict.get(cat_name, 0)
        income_by_category.append({
            'category_name': cat_name,
            'color': row['color'] or '#28a745',
            'actual': actual,
            'budget': budget,
            'ly_amount': ly_amount
        })
        total_income += actual
        total_income_budget += budget

    ly_total_income = sum(ly_income_dict.values())

    # ---- EXPENSES ----
    cursor.execute("""
        SELECT c.id as category_id, c.name as category_name, c.color, SUM(e.amount) as actual
        FROM expenses e
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.archived = 0 AND e.date >= %s AND e.date < %s
        GROUP BY c.id, c.name, c.color ORDER BY actual DESC
    """, (start_date, end_date))
    exp_rows = cursor.fetchall()

    # Expense budgets
    exp_budget_dict = {}
    if view_type == 'month':
        cursor.execute("""
            SELECT category_id, amount FROM budget WHERE month = %s
        """, (selected_month,))
        for row in cursor.fetchall():
            exp_budget_dict[row['category_id']] = float(row['amount'])

    # Subcategory actuals
    cursor.execute("""
        SELECT e.category_id, sc.id as sub_id, sc.name, SUM(e.amount) as actual
        FROM expenses e
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        WHERE e.archived = 0 AND e.date >= %s AND e.date < %s AND e.subcategory_id IS NOT NULL
        GROUP BY e.category_id, sc.id, sc.name ORDER BY actual DESC
    """, (start_date, end_date))
    sub_actuals = cursor.fetchall()

    # Subcategory budgets
    sub_budget_dict = {}
    if view_type == 'month':
        cursor.execute("SELECT subcategory_id, amount FROM budget_subcategory WHERE month = %s", (selected_month,))
        for row in cursor.fetchall():
            sub_budget_dict[row['subcategory_id']] = float(row['amount'])

    # Build sub lookup by category
    sub_lookup = {}
    for sub in sub_actuals:
        cat_id = sub['category_id']
        if cat_id not in sub_lookup:
            sub_lookup[cat_id] = []
        sub_lookup[cat_id].append({
            'subcategory_id': sub['sub_id'],
            'name': sub['name'],
            'actual': float(sub['actual']),
            'budget': sub_budget_dict.get(sub['sub_id'], 0)
        })

    # Last year expenses
    ly_exp_dict = {}
    if ly_start and ly_end:
        cursor.execute("""
            SELECT c.name as category_name, SUM(e.amount) as total
            FROM expenses e LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.archived = 0 AND e.date >= %s AND e.date < %s
            GROUP BY c.name
        """, (ly_start, ly_end))
        for row in cursor.fetchall():
            ly_exp_dict[row['category_name']] = float(row['total'])

    expenses_by_category = []
    total_expenses = 0
    total_expenses_budget = 0
    for row in exp_rows:
        cat_name = row['category_name'] or 'Uncategorized'
        actual = float(row['actual'])
        budget = exp_budget_dict.get(row['category_id'], 0)
        ly_amount = ly_exp_dict.get(cat_name, 0)
        expenses_by_category.append({
            'category_name': cat_name,
            'color': row['color'] or '#6c757d',
            'actual': actual,
            'budget': budget,
            'ly_amount': ly_amount,
            'subcategories': sub_lookup.get(row['category_id'], [])
        })
        total_expenses += actual
        total_expenses_budget += budget

    ly_total_expenses = sum(ly_exp_dict.values())
    net = total_income - total_expenses

    # Years for selector
    cursor.execute("""
        SELECT DISTINCT EXTRACT(YEAR FROM date)::int as yr FROM expenses
        UNION SELECT DISTINCT EXTRACT(YEAR FROM date)::int as yr FROM income
        ORDER BY yr DESC
    """)
    years = [r['yr'] for r in cursor.fetchall()] or [datetime.now().year]

    # Tax summary — group by tax rate name
    tax_summary = []
    try:
        cursor.execute(f"""
            SELECT tr.name as rate_name, tr.rate, SUM(e.tax_amount) as total_tax
            FROM expenses e
            JOIN tax_rates tr ON e.tax_rate_id = tr.id
            WHERE e.archived = 0 AND e.date >= %s AND e.date{date_op if "date_op" in dir() else "<"} %s
            AND e.tax_amount IS NOT NULL AND e.tax_amount > 0
            GROUP BY tr.name, tr.rate
            ORDER BY tr.rate DESC
        """, (start_date, end_date))
        tax_summary = cursor.fetchall()
    except Exception:
        pass  # tax columns may not exist yet

    total_tax_paid = sum(float(r['total_tax']) for r in tax_summary)

    cursor.close()
    conn.close()

    return render_template('pnl.html',
                         tax_summary=tax_summary,
                         total_tax_paid=total_tax_paid,
                         view_type=view_type,
                         selected_month=selected_month,
                         selected_year=selected_year,
                         date_from=date_from,
                         date_to=date_to,
                         period_label=period_label,
                         start_date=start_date,
                         end_date=end_date,
                         income_by_category=income_by_category,
                         expenses_by_category=expenses_by_category,
                         total_income=total_income,
                         total_income_budget=total_income_budget,
                         total_expenses=total_expenses,
                         total_expenses_budget=total_expenses_budget,
                         net=net,
                         ly_total_income=ly_total_income,
                         ly_total_expenses=ly_total_expenses,
                         years=years)


# ============= P&L DETAIL POPUP =============
@app.route('/pnl/detail')
@login_required
def pnl_detail():
    """Returns JSON list of transactions for a category/subcategory in a date range."""
    category_id = request.args.get('category_id')
    subcategory_id = request.args.get('subcategory_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    record_type = request.args.get('type', 'expense')  # 'expense' or 'income'

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if record_type == 'income':
        cursor.execute("""
            SELECT i.date, i.description, i.amount, i.notes,
                   s.name as source_name, ic.name as category_name
            FROM income i
            LEFT JOIN sources s ON i.source_id = s.id
            LEFT JOIN income_categories ic ON i.category_id = ic.id
            WHERE i.archived = 0 AND i.date >= %s AND i.date < %s
            AND ic.id = %s
            ORDER BY i.date DESC
        """, (start_date, end_date, category_id))
    else:
        if subcategory_id:
            cursor.execute("""
                SELECT e.date, e.description, e.amount, e.notes,
                       s.name as source_name, c.name as category_name,
                       sc.name as subcategory_name, v.name as vendor_name
                FROM expenses e
                LEFT JOIN sources s ON e.source_id = s.id
                LEFT JOIN categories c ON e.category_id = c.id
                LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
                LEFT JOIN vendors v ON e.vendor_id = v.id
                WHERE e.archived = 0 AND e.date >= %s AND e.date < %s
                AND e.subcategory_id = %s
                ORDER BY e.date DESC
            """, (start_date, end_date, subcategory_id))
        else:
            cursor.execute("""
                SELECT e.date, e.description, e.amount, e.notes,
                       s.name as source_name, c.name as category_name,
                       sc.name as subcategory_name, v.name as vendor_name
                FROM expenses e
                LEFT JOIN sources s ON e.source_id = s.id
                LEFT JOIN categories c ON e.category_id = c.id
                LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
                LEFT JOIN vendors v ON e.vendor_id = v.id
                WHERE e.archived = 0 AND e.date >= %s AND e.date < %s
                AND e.category_id = %s
                ORDER BY e.date DESC
            """, (start_date, end_date, category_id))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    transactions = []
    for r in rows:
        transactions.append({
            'date': str(r['date']),
            'description': r.get('description') or '—',
            'category_name': r.get('category_name') or '—',
            'subcategory_name': r.get('subcategory_name') or '',
            'vendor_name': r.get('vendor_name') or '',
            'source_name': r.get('source_name') or '—',
            'notes': r.get('notes') or '',
            'amount': float(r['amount'])
        })

    total = sum(t['amount'] for t in transactions)
    return jsonify({'transactions': transactions, 'total': total})


# ============= SPLIT TRANSACTIONS =============
@app.route('/expenses/split/<int:expense_id>', methods=['GET'])
@login_required
def split_transaction(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get the parent expense (or the child — find the root)
    cursor.execute("""
        SELECT e.*, s.name as source_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        WHERE e.id = %s
    """, (expense_id,))
    expense = cursor.fetchone()

    if not expense:
        cursor.close(); conn.close()
        return "Expense not found", 404

    # If this is a child split, find the parent
    if expense['parent_transaction_id']:
        parent_id = expense['parent_transaction_id']
        cursor.execute("""
            SELECT e.*, s.name as source_name FROM expenses e
            LEFT JOIN sources s ON e.source_id = s.id
            WHERE e.id = %s
        """, (parent_id,))
        expense = cursor.fetchone()
        expense_id = parent_id

    # Get existing child splits
    cursor.execute("""
        SELECT e.*, c.name as category_name, sc.name as subcategory_name, v.name as vendor_name
        FROM expenses e
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        WHERE e.parent_transaction_id = %s
        ORDER BY e.id
    """, (expense_id,))
    existing_splits = cursor.fetchall()

    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name')
    subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name')
    vendors = cursor.fetchall()
    cursor.close(); conn.close()

    # Build JSON for JS
    splits_json = json.dumps([{
        'amount': float(s['amount']),
        'category_id': s['category_id'],
        'subcategory_id': s['subcategory_id'],
        'vendor_id': s['vendor_id'],
        'description': s['description'] or '',
        'notes': s['notes'] or ''
    } for s in existing_splits])

    categories_json = json.dumps([{'id': c['id'], 'name': c['name']} for c in categories])
    subcategories_json = json.dumps([{'id': s['id'], 'name': s['name'], 'category_id': s['category_id']} for s in subcategories])
    vendors_json = json.dumps([{'id': v['id'], 'name': v['name']} for v in vendors])

    return render_template('split_transaction.html',
                         expense=expense,
                         splits_json=splits_json,
                         categories_json=categories_json,
                         subcategories_json=subcategories_json,
                         vendors_json=vendors_json)

@app.route('/expenses/split/<int:expense_id>', methods=['POST'])
@login_required
def save_split_transaction(expense_id):
    data = request.get_json()
    splits = data.get('splits', [])

    if not splits:
        return jsonify({'success': False, 'error': 'No splits provided'})

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get original expense
    cursor.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,))
    original = cursor.fetchone()
    if not original:
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': 'Expense not found'})

    # Validate total
    total = sum(float(s['amount']) for s in splits)
    if abs(total - float(original['amount'])) > 0.01:
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': f'Split total ${total:.2f} must equal original ${float(original["amount"]):.2f}'})

    # Delete any existing child splits
    cursor.execute('DELETE FROM expenses WHERE parent_transaction_id = %s', (expense_id,))

    # Mark original as parent
    cursor.execute('UPDATE expenses SET is_split = 1 WHERE id = %s', (expense_id,))

    # Insert child splits
    for split in splits:
        cursor.execute("""
            INSERT INTO expenses
                (date, source_id, description, category_id, subcategory_id,
                 vendor_id, amount, notes, parent_transaction_id, is_split, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 2, CURRENT_TIMESTAMP)
        """, (
            original['date'],
            original['source_id'],
            split.get('description') or original['description'],
            split.get('category_id') or None,
            split.get('subcategory_id') or None,
            split.get('vendor_id') or None,
            float(split['amount']),
            split.get('notes', ''),
            expense_id
        ))

    conn.commit()
    cursor.close(); conn.close()
    return jsonify({'success': True})

@app.route('/expenses/split/reset/<int:expense_id>', methods=['POST'])
@login_required
def reset_split_transaction(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM expenses WHERE parent_transaction_id = %s', (expense_id,))
    cursor.execute('UPDATE expenses SET is_split = 0 WHERE id = %s', (expense_id,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({'success': True})


# ============= RECEIPTS =============
@app.route('/expenses/<int:expense_id>/receipt', methods=['POST'])
@login_required
def upload_receipt(expense_id):
    if 'receipt' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'})
    
    file = request.files['receipt']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'})
    
    allowed = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        return jsonify({'success': False, 'error': 'File type not allowed'})
    
    # Read file data
    file_data = file.read()
    
    # Limit to 10MB
    if len(file_data) > 10 * 1024 * 1024:
        return jsonify({'success': False, 'error': 'File too large (max 10MB)'})
    
    mime_type = file.content_type or f'image/{ext}'
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE expenses SET receipt_data = %s, receipt_mime_type = %s WHERE id = %s
    """, (psycopg2.Binary(file_data), mime_type, expense_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/expenses/<int:expense_id>/receipt', methods=['GET'])
@login_required
def view_receipt(expense_id):
    from flask import Response
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT receipt_data, receipt_mime_type FROM expenses WHERE id = %s', (expense_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not row or not row['receipt_data']:
        return "No receipt found", 404
    
    return Response(
        bytes(row['receipt_data']),
        mimetype=row['receipt_mime_type'] or 'image/jpeg'
    )

@app.route('/expenses/<int:expense_id>/receipt/delete', methods=['POST'])
@login_required
def delete_receipt(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE expenses SET receipt_data = NULL, receipt_mime_type = NULL WHERE id = %s", (expense_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'success': True})


# ============= USER MANAGEMENT =============
@app.route('/manage/users')
@login_required
def manage_users():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT id, username FROM users ORDER BY username')
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_users.html', users=users)

@app.route('/manage/users/add', methods=['POST'])
@login_required
def add_user():
    if session.get('username') != 'admin':
        return redirect(url_for('manage_users'))
    username = request.form['username'].strip()
    password = request.form['password']
    if not username or not password:
        return redirect(url_for('manage_users'))
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (username, password) VALUES (%s, %s)', (username, hashed))
        conn.commit()
    except Exception:
        conn.rollback()
    cursor.close()
    conn.close()
    return redirect(url_for('manage_users'))

@app.route('/manage/users/delete/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    # Only admin can delete users
    if session.get('username') != 'admin':
        return redirect(url_for('manage_users'))
    # Prevent deleting yourself
    if user_id == session.get('user_id'):
        return redirect(url_for('manage_users'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = %s', (user_id,))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('manage_users'))

@app.route('/manage/users/change-password', methods=['POST'])
@login_required
def change_password():
    user_id = int(request.form['user_id'])
    new_password = request.form['new_password']
    # Users can only change their own password
    if user_id != session.get('user_id'):
        return redirect(url_for('manage_users'))
    if not new_password:
        return redirect(url_for('manage_users'))
    hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET password = %s WHERE id = %s', (hashed, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('manage_users'))



@app.route('/reports')
@login_required
def reports():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    cursor.execute('SELECT * FROM income_categories ORDER BY name')
    income_categories = cursor.fetchall()
    cursor.execute("""
        SELECT DISTINCT EXTRACT(YEAR FROM date)::int as yr FROM expenses
        UNION SELECT DISTINCT EXTRACT(YEAR FROM date)::int as yr FROM income
        ORDER BY yr DESC
    """)
    years = [r['yr'] for r in cursor.fetchall()] or [datetime.now().year]
    cursor.close(); conn.close()
    return render_template('reports.html',
                         categories=categories,
                         income_categories=income_categories,
                         years=years,
                         current_month=datetime.now().strftime('%Y-%m'))

# ============= PDF REPORTS =============
def make_pdf_response(buffer, filename):
    from flask import Response
    buffer.seek(0)
    return Response(
        buffer.read(),
        mimetype='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )

def pdf_header(doc_title, period_label):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    elements = []
    title_style = ParagraphStyle('title', fontSize=18, fontName='Helvetica-Bold',
                                  alignment=TA_CENTER, spaceAfter=6)
    sub_style = ParagraphStyle('sub', fontSize=11, fontName='Helvetica',
                                alignment=TA_CENTER, spaceAfter=16, textColor=colors.grey)
    elements.append(Paragraph(doc_title, title_style))
    elements.append(Paragraph(period_label, sub_style))
    return elements

@app.route('/reports/expenses/pdf')
@login_required
def expense_report_pdf():
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO

    # Get filters (same as view_expenses)
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    category_id  = request.args.get('category_id', '')
    source_id    = request.args.get('source_id', '')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = """
        SELECT e.date, e.description, s.name as source_name,
               c.name as category_name, sc.name as subcategory_name,
               v.name as vendor_name, e.amount, e.notes
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        WHERE e.archived = 0 AND (e.is_split = 0 OR e.is_split = 2)
    """
    params = []
    if date_from: query += ' AND e.date >= %s'; params.append(date_from)
    if date_to:   query += ' AND e.date <= %s'; params.append(date_to)
    if category_id: query += ' AND e.category_id = %s'; params.append(category_id)
    if source_id:   query += ' AND e.source_id = %s'; params.append(source_id)
    query += ' ORDER BY e.date DESC'
    cursor.execute(query, params)
    expenses = cursor.fetchall()
    cursor.close(); conn.close()

    total = sum(float(e['amount']) for e in expenses)
    period = f"{date_from or 'All'} to {date_to or 'All'}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)

    elements = pdf_header('Expense Report', period)

    # Table
    data = [['Date', 'Description', 'Source', 'Category', 'Subcategory', 'Vendor', 'Amount']]
    for e in expenses:
        data.append([
            str(e['date']),
            (e['description'] or '')[:35],
            e['source_name'] or '',
            e['category_name'] or '',
            e['subcategory_name'] or '',
            e['vendor_name'] or '',
            f"${float(e['amount']):.2f}"
        ])
    data.append(['', '', '', '', '', 'TOTAL', f"${total:.2f}"])

    col_widths = [65, 155, 80, 85, 85, 85, 65]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('ALIGN',      (6,0), (6,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f8f9fa')]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8f5e9')),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
        ('TEXTCOLOR',  (6,-1), (6,-1), colors.HexColor('#c0392b')),
    ]))
    elements.append(t)
    doc.build(elements)
    return make_pdf_response(buffer, f'expense_report_{date_from or "all"}.pdf')


@app.route('/reports/income/pdf')
@login_required
def income_report_pdf():
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from io import BytesIO

    date_from   = request.args.get('date_from', '')
    date_to     = request.args.get('date_to', '')
    category_id = request.args.get('category_id', '')

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    query = """
        SELECT i.date, i.description, s.name as source_name,
               ic.name as category_name, i.amount, i.notes
        FROM income i
        LEFT JOIN sources s ON i.source_id = s.id
        LEFT JOIN income_categories ic ON i.category_id = ic.id
        WHERE i.archived = 0
    """
    params = []
    if date_from: query += ' AND i.date >= %s'; params.append(date_from)
    if date_to:   query += ' AND i.date <= %s'; params.append(date_to)
    if category_id: query += ' AND i.category_id = %s'; params.append(category_id)
    query += ' ORDER BY i.date DESC'
    cursor.execute(query, params)
    income_list = cursor.fetchall()
    cursor.close(); conn.close()

    total = sum(float(i['amount']) for i in income_list)
    period = f"{date_from or 'All'} to {date_to or 'All'}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter),
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    elements = pdf_header('Income Report', period)

    data = [['Date', 'Description', 'Source', 'Category', 'Amount', 'Notes']]
    for i in income_list:
        data.append([
            str(i['date']),
            (i['description'] or '')[:45],
            i['source_name'] or '',
            i['category_name'] or '',
            f"${float(i['amount']):.2f}",
            (i['notes'] or '')[:30]
        ])
    data.append(['', '', '', 'TOTAL', f"${total:.2f}", ''])

    col_widths = [65, 195, 100, 110, 80, 120]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a6b3c')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('ALIGN',      (4,0), (4,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f0faf4')]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8f5e9')),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
        ('TEXTCOLOR',  (4,-1), (4,-1), colors.HexColor('#1a6b3c')),
    ]))
    elements.append(t)
    doc.build(elements)
    return make_pdf_response(buffer, f'income_report_{date_from or "all"}.pdf')


@app.route('/reports/budget/pdf')
@login_required
def budget_report_pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from io import BytesIO

    month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    y, m = int(month[:4]), int(month[5:7])
    month_start = f'{y}-{m:02d}-01'
    month_end = f'{y+1}-01-01' if m == 12 else f'{y}-{m+1:02d}-01'

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    cursor.execute('SELECT * FROM budget WHERE month = %s', (month,))
    cat_budgets = {r['category_id']: float(r['amount']) for r in cursor.fetchall()}
    cursor.execute('SELECT category_id, SUM(amount) as total FROM expenses WHERE archived=0 AND date>=%s AND date<%s GROUP BY category_id', (month_start, month_end))
    cat_spending = {r['category_id']: float(r['total']) for r in cursor.fetchall()}
    cursor.close(); conn.close()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    elements = pdf_header('Budget Report', month)

    data = [['Category', 'Budgeted', 'Spent', 'Remaining', '% Used']]
    total_budget = total_spent = 0
    for cat in categories:
        budgeted = cat_budgets.get(cat['id'], 0)
        spent    = cat_spending.get(cat['id'], 0)
        remaining = budgeted - spent
        pct = f"{(spent/budgeted*100):.0f}%" if budgeted > 0 else '—'
        data.append([
            cat['name'],
            f"${budgeted:.2f}" if budgeted > 0 else '—',
            f"${spent:.2f}" if spent > 0 else '—',
            f"${remaining:.2f}" if budgeted > 0 else '—',
            pct
        ])
        total_budget += budgeted
        total_spent  += spent

    data.append(['TOTAL', f"${total_budget:.2f}", f"${total_spent:.2f}",
                 f"${total_budget - total_spent:.2f}",
                 f"{(total_spent/total_budget*100):.0f}%" if total_budget > 0 else '—'])

    col_widths = [180, 90, 90, 90, 90]
    t = Table(data, colWidths=col_widths, repeatRows=1)

    style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f8f9fa')]),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#e8f5e9')),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#dee2e6')),
    ]
    # Red for over budget rows
    for i, cat in enumerate(categories, 1):
        budgeted = cat_budgets.get(cat['id'], 0)
        spent    = cat_spending.get(cat['id'], 0)
        if budgeted > 0 and spent > budgeted:
            style.append(('TEXTCOLOR', (3,i), (3,i), colors.HexColor('#c0392b')))
            style.append(('TEXTCOLOR', (4,i), (4,i), colors.HexColor('#c0392b')))

    t.setStyle(TableStyle(style))
    elements.append(t)
    doc.build(elements)
    return make_pdf_response(buffer, f'budget_report_{month}.pdf')


@app.route('/reports/pnl/pdf')
@login_required
def pnl_report_pdf():
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from io import BytesIO

    view_type      = request.args.get('view_type', 'month')
    selected_month = request.args.get('month', datetime.now().strftime('%Y-%m'))
    selected_year  = int(request.args.get('year', datetime.now().year))
    date_from      = request.args.get('date_from', '')
    date_to        = request.args.get('date_to', '')

    if view_type == 'month':
        y, m = int(selected_month[:4]), int(selected_month[5:7])
        start_date = f'{y}-{m:02d}-01'
        end_date   = f'{y+1}-01-01' if m == 12 else f'{y}-{m+1:02d}-01'
        period     = selected_month
        use_lt     = True   # use < for month/year (end_date is first day of NEXT period)
    elif view_type == 'year':
        start_date = f'{selected_year}-01-01'
        end_date   = f'{selected_year+1}-01-01'
        period     = str(selected_year)
        use_lt     = True
    else:
        # Custom range — validate dates
        if not date_from or not date_to:
            return "Please provide both a start and end date.", 400
        start_date = date_from
        end_date   = date_to
        period     = f"{date_from} to {date_to}"
        use_lt     = False  # use <= for custom range (end_date is inclusive)

    # Build date comparison operator
    date_op = '<' if use_lt else '<='

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cursor.execute(f"""
        SELECT ic.name as category_name, SUM(i.amount) as total
        FROM income i LEFT JOIN income_categories ic ON i.category_id = ic.id
        WHERE i.archived=0 AND i.date>=%s AND i.date{date_op}%s
        GROUP BY ic.name ORDER BY total DESC
    """, (start_date, end_date))
    income_rows = cursor.fetchall()
    total_income = sum(float(r['total']) for r in income_rows)

    cursor.execute(f"""
        SELECT c.name as category_name, SUM(e.amount) as total
        FROM expenses e LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.archived=0 AND e.date>=%s AND e.date{date_op}%s
        GROUP BY c.name ORDER BY total DESC
    """, (start_date, end_date))
    expense_rows = cursor.fetchall()
    total_expenses = sum(float(r['total']) for r in expense_rows)
    cursor.close(); conn.close()

    net = total_income - total_expenses

    # Tax summary
    tax_rows_pdf = []
    try:
        cursor.execute(f"""
            SELECT tr.name as rate_name, SUM(e.tax_amount) as total_tax
            FROM expenses e
            JOIN tax_rates tr ON e.tax_rate_id = tr.id
            WHERE e.archived=0 AND e.date>=%s AND e.date{date_op}%s
            AND e.tax_amount IS NOT NULL AND e.tax_amount > 0
            GROUP BY tr.name, tr.rate ORDER BY tr.rate DESC
        """, (start_date, end_date))
        tax_rows_pdf = cursor.fetchall()
    except Exception:
        pass
    total_tax_pdf = sum(float(r['total_tax']) for r in tax_rows_pdf)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    elements = pdf_header('Profit & Loss Statement', period)

    # Income section
    data = [['INCOME', 'Amount']]
    for r in income_rows:
        data.append([r['category_name'] or 'Uncategorized', f"${float(r['total']):.2f}"])
    data.append(['Total Income', f"${total_income:.2f}"])
    data.append(['', ''])  # spacer row
    # Expense section
    data.append(['EXPENSES', 'Amount'])
    for r in expense_rows:
        data.append([r['category_name'] or 'Uncategorized', f"${float(r['total']):.2f}"])
    data.append(['Total Expenses', f"${total_expenses:.2f}"])
    data.append(['', ''])
    data.append(['NET ' + ('SURPLUS' if net >= 0 else 'DEFICIT'), f"${abs(net):.2f}"])

    # Tax summary section
    if tax_rows_pdf:
        data.append(['', ''])
        data.append(['TAX SUMMARY', ''])
        for r in tax_rows_pdf:
            data.append([r['rate_name'], f"${float(r['total_tax']):.2f}"])
        data.append(['Total Tax Paid', f"${total_tax_pdf:.2f}"])

    col_widths = [360, 120]
    t = Table(data, colWidths=col_widths)

    income_end  = len(income_rows) + 1
    expense_start = income_end + 2
    expense_end   = expense_start + len(expense_rows)
    net_row = len(data) - 1

    style = [
        ('FONTSIZE',  (0,0), (-1,-1), 10),
        ('GRID',      (0,0), (-1,-1), 0.3, colors.HexColor('#dee2e6')),
        ('ALIGN',     (1,0), (1,-1), 'RIGHT'),
        # Income header
        ('BACKGROUND',(0,0),(-1,0), colors.HexColor('#1a6b3c')),
        ('TEXTCOLOR', (0,0),(-1,0), colors.white),
        ('FONTNAME',  (0,0),(-1,0), 'Helvetica-Bold'),
        # Income total
        ('BACKGROUND',(0,income_end),(-1,income_end), colors.HexColor('#e8f5e9')),
        ('FONTNAME',  (0,income_end),(-1,income_end), 'Helvetica-Bold'),
        # Expense header
        ('BACKGROUND',(0,expense_start),(-1,expense_start), colors.HexColor('#c0392b')),
        ('TEXTCOLOR', (0,expense_start),(-1,expense_start), colors.white),
        ('FONTNAME',  (0,expense_start),(-1,expense_start), 'Helvetica-Bold'),
        # Expense total
        ('BACKGROUND',(0,expense_end),(-1,expense_end), colors.HexColor('#fdecea')),
        ('FONTNAME',  (0,expense_end),(-1,expense_end), 'Helvetica-Bold'),
        # Net row
        ('BACKGROUND',(0,net_row),(-1,net_row),
         colors.HexColor('#e8f5e9') if net >= 0 else colors.HexColor('#fdecea')),
        ('FONTNAME',  (0,net_row),(-1,net_row), 'Helvetica-Bold'),
        ('FONTSIZE',  (0,net_row),(-1,net_row), 12),
        ('TEXTCOLOR', (1,net_row),(1,net_row),
         colors.HexColor('#1a6b3c') if net >= 0 else colors.HexColor('#c0392b')),
        # Alternating rows for income
        ('ROWBACKGROUNDS', (0,1),(-1,income_end-1), [colors.white, colors.HexColor('#f0faf4')]),
        # Alternating rows for expenses
        ('ROWBACKGROUNDS', (0,expense_start+1),(-1,expense_end-1), [colors.white, colors.HexColor('#fef9f9')]),
    ]
    t.setStyle(TableStyle(style))
    elements.append(t)
    doc.build(elements)
    return make_pdf_response(buffer, f'pnl_{period}.pdf')


# ============= TAX RATES =============
@app.route('/manage/tax-rates')
@login_required
def manage_tax_rates():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM tax_rates ORDER BY display_order, name')
    tax_rates = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('manage_tax_rates.html', tax_rates=tax_rates)

@app.route('/manage/tax-rates/add', methods=['POST'])
@login_required
def add_tax_rate():
    name = request.form['name'].strip()
    rate = float(request.form['rate'])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, 99, 1)',
                  (name, rate))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_tax_rates'))

@app.route('/manage/tax-rates/toggle/<int:rate_id>', methods=['POST'])
@login_required
def toggle_tax_rate(rate_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE tax_rates SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = %s', (rate_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_tax_rates'))

@app.route('/manage/tax-rates/delete/<int:rate_id>', methods=['POST'])
@login_required
def delete_tax_rate(rate_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tax_rates WHERE id = %s', (rate_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_tax_rates'))


# ============= CSV IMPORT =============
@app.route('/csv-import', methods=['GET', 'POST'])
@login_required
def csv_import():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name')
    sources = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    # Load saved templates
    templates = []
    try:
        cursor.execute('SELECT * FROM csv_templates ORDER BY name')
        templates = cursor.fetchall()
    except Exception:
        pass
    cursor.close(); conn.close()
    return render_template('csv_import.html',
                         sources=sources,
                         categories=categories,
                         templates=templates)

@app.route('/csv-import/process', methods=['POST'])
@login_required
def csv_import_process():
    data = request.get_json()
    rows = data.get('rows', [])
    source_id = data.get('source_id')
    category_id = data.get('category_id')

    conn = get_db_connection()
    cursor = conn.cursor()

    expenses_imported = 0
    income_imported = 0
    errors = 0

    from datetime import datetime as dt

    for row in rows:
        try:
            date_str = row['date'].strip()
            parsed_date = None
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%m-%d-%Y',
                        '%Y/%m/%d', '%b %d, %Y', '%d-%b-%Y', '%m/%d/%y']:
                try:
                    parsed_date = dt.strptime(date_str, fmt).strftime('%Y-%m-%d')
                    break
                except ValueError:
                    continue

            if not parsed_date:
                errors += 1
                continue

            amount = float(row['amount'])
            description = row['description'][:255]

            if row['type'] == 'expense':
                # Duplicate check — same date, amount, description
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM expenses
                    WHERE date = %s AND amount = %s
                    AND LOWER(description) = LOWER(%s)
                """, (parsed_date, amount, description))
                if cursor.fetchone()['cnt'] > 0:
                    errors += 1  # count as skipped duplicate
                    continue
                cursor.execute("""
                    INSERT INTO expenses
                        (date, source_id, description, category_id, amount, created_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (parsed_date, source_id, description, category_id, amount))
                expenses_imported += 1
            else:
                # Duplicate check for income
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM income
                    WHERE date = %s AND amount = %s
                    AND LOWER(description) = LOWER(%s)
                """, (parsed_date, amount, description))
                if cursor.fetchone()['cnt'] > 0:
                    errors += 1
                    continue
                cursor.execute("""
                    INSERT INTO income
                        (date, source_id, description, amount, created_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (parsed_date, source_id, description, amount))
                income_imported += 1
        except Exception as e:
            errors += 1
            continue

    conn.commit()
    cursor.close()
    conn.close()

    return jsonify({
        'success': True,
        'expenses_imported': expenses_imported,
        'income_imported': income_imported,
        'errors': errors
    })

@app.route('/csv-import/template/save', methods=['POST'])
@login_required
def csv_template_save():
    data = request.get_json()
    name = data.get('name', '').strip()
    config = data.get('config', {})
    if not name:
        return jsonify({'success': False})
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO csv_templates (name, config_json)
            VALUES (%s, %s)
            ON CONFLICT (name) DO UPDATE SET config_json = EXCLUDED.config_json
        """, (name, json.dumps(config)))
        conn.commit()
    except Exception:
        conn.rollback()
    cursor.close(); conn.close()
    return jsonify({'success': True})

@app.route('/csv-import/template/delete/<int:template_id>', methods=['POST'])
@login_required
def csv_template_delete(template_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM csv_templates WHERE id = %s', (template_id,))
    conn.commit()
    cursor.close(); conn.close()
    return jsonify({'success': True})


# ============= ADMIN TOOLS =============
@app.route('/admin/tools')
@login_required
def admin_tools():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    stats = {}
    for table in ['expenses', 'income', 'categories', 'subcategories',
                  'vendors', 'sources', 'budget', 'tax_rates', 'users']:
        try:
            cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
            stats[table] = cursor.fetchone()['count']
        except Exception:
            stats[table] = 0
    cursor.close(); conn.close()
    return render_template('admin_tools.html', stats=stats)

@app.route('/admin/backup/expenses')
@login_required
def backup_expenses():
    import csv
    from io import StringIO
    from flask import Response
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT e.date, e.description, e.amount, e.notes,
               s.name as source, c.name as category,
               sc.name as subcategory, v.name as vendor,
               tr.name as tax_rate, e.subtotal, e.tax_amount
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        LEFT JOIN tax_rates tr ON e.tax_rate_id = tr.id
        WHERE e.archived = 0 AND (e.is_split = 0 OR e.is_split = 2)
        ORDER BY e.date DESC
    """)
    rows = cursor.fetchall()
    cursor.close(); conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date','Description','Amount','Source','Category',
                     'Subcategory','Vendor','Tax Rate','Subtotal','Tax Amount','Notes'])
    for r in rows:
        writer.writerow([r['date'], r['description'], r['amount'], r['source'],
                        r['category'], r['subcategory'], r['vendor'],
                        r['tax_rate'], r['subtotal'], r['tax_amount'], r['notes']])

    output.seek(0)
    filename = f'expenses_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return Response(output.read(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.route('/admin/backup/income')
@login_required
def backup_income():
    import csv
    from io import StringIO
    from flask import Response
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT i.date, i.description, i.amount, i.notes,
               s.name as source, ic.name as category
        FROM income i
        LEFT JOIN sources s ON i.source_id = s.id
        LEFT JOIN income_categories ic ON i.category_id = ic.id
        WHERE i.archived = 0
        ORDER BY i.date DESC
    """)
    rows = cursor.fetchall()
    cursor.close(); conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date','Description','Amount','Source','Category','Notes'])
    for r in rows:
        writer.writerow([r['date'], r['description'], r['amount'],
                        r['source'], r['category'], r['notes']])

    output.seek(0)
    filename = f'income_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return Response(output.read(), mimetype='text/csv',
                   headers={'Content-Disposition': f'attachment; filename="{filename}"'})

@app.route('/admin/clear', methods=['POST'])
@login_required
def admin_clear():
    if session.get('username') != 'admin':
        return jsonify({'success': False, 'error': 'Admin only'})
    
    action = request.form.get('action')
    confirm = request.form.get('confirm', '').strip().upper()
    
    if confirm != 'DELETE':
        return jsonify({'success': False, 'error': 'Type DELETE to confirm'})

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if action == 'expenses_only':
            cursor.execute('DELETE FROM expenses')
            msg = 'All expenses deleted'
        elif action == 'income_only':
            cursor.execute('DELETE FROM income')
            msg = 'All income deleted'
        elif action == 'transactions':
            cursor.execute('DELETE FROM expenses')
            cursor.execute('DELETE FROM income')
            cursor.execute('DELETE FROM budget')
            msg = 'All transactions and budgets deleted'
        elif action == 'full_reset':
            for table in ['expenses', 'income', 'budget', 'budget_subcategory',
                         'subcategories', 'vendors', 'categories', 'income_categories',
                         'sources', 'tax_rates', 'csv_templates']:
                cursor.execute(f'DELETE FROM {table}')
            msg = 'Full reset complete — all data deleted'
        else:
            conn.rollback()
            cursor.close(); conn.close()
            return jsonify({'success': False, 'error': 'Unknown action'})

        conn.commit()
        cursor.close(); conn.close()
        return jsonify({'success': True, 'message': msg})
    except Exception as e:
        conn.rollback()
        cursor.close(); conn.close()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/csv-import/check-duplicates', methods=['POST'])
@login_required
def check_duplicates():
    """Check which rows already exist in the database."""
    data = request.get_json()
    rows = data.get('rows', [])
    duplicate_indices = []

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    for i, row in enumerate(rows):
        try:
            if row['type'] == 'expense':
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM expenses
                    WHERE date = %s AND amount = %s
                    AND LOWER(description) = LOWER(%s)
                """, (row['date'], float(row['amount']), row['description']))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM income
                    WHERE date = %s AND amount = %s
                    AND LOWER(description) = LOWER(%s)
                """, (row['date'], float(row['amount']), row['description']))

            if cursor.fetchone()['cnt'] > 0:
                duplicate_indices.append(i)
        except Exception:
            pass

    cursor.close(); conn.close()
    return jsonify({'duplicates': duplicate_indices})


# ============= ARCHIVE =============
@app.route('/expenses/archive/<int:expense_id>', methods=['POST'])
@login_required
def archive_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE expenses SET archived = 1 WHERE id = %s', (expense_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(request.referrer or url_for('view_expenses'))

@app.route('/expenses/unarchive/<int:expense_id>', methods=['POST'])
@login_required
def unarchive_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE expenses SET archived = 0 WHERE id = %s', (expense_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(request.referrer or url_for('view_expenses'))

@app.route('/income/archive/<int:income_id>', methods=['POST'])
@login_required
def archive_income(income_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE income SET archived = 1 WHERE id = %s', (income_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(request.referrer or url_for('view_income'))

@app.route('/income/unarchive/<int:income_id>', methods=['POST'])
@login_required
def unarchive_income(income_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE income SET archived = 0 WHERE id = %s', (income_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(request.referrer or url_for('view_income'))

@app.route('/expenses/bulk-archive', methods=['POST'])
@login_required
def bulk_archive_expenses():
    months = int(request.form.get('months', 6))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE expenses SET archived = 1
        WHERE date < CURRENT_DATE - INTERVAL '%s months'
        AND archived = 0
    """, (months,))
    count = cursor.rowcount
    conn.commit(); cursor.close(); conn.close()
    return jsonify({'success': True, 'count': count})

# ============= RECURRING EXPENSES =============
@app.route('/recurring')
@login_required
def recurring():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT r.*, s.name as source_name, c.name as category_name,
               sc.name as subcategory_name, v.name as vendor_name
        FROM recurring_expenses r
        LEFT JOIN sources s ON r.source_id = s.id
        LEFT JOIN categories c ON r.category_id = c.id
        LEFT JOIN subcategories sc ON r.subcategory_id = sc.id
        LEFT JOIN vendors v ON r.vendor_id = v.id
        ORDER BY r.is_active DESC, r.description
    """)
    recurring_expenses = cursor.fetchall()
    cursor.execute("""
        SELECT r.*, s.name as source_name, ic.name as category_name
        FROM recurring_income r
        LEFT JOIN sources s ON r.source_id = s.id
        LEFT JOIN income_categories ic ON r.category_id = ic.id
        ORDER BY r.is_active DESC, r.description
    """)
    recurring_income = cursor.fetchall()
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.execute('SELECT * FROM income_categories ORDER BY name'); income_categories = cursor.fetchall()
    cursor.close(); conn.close()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('recurring.html',
                         recurring_expenses=recurring_expenses,
                         recurring_income=recurring_income,
                         sources=sources, categories=categories,
                         subcategories=subcategories, vendors=vendors,
                         income_categories=income_categories, today=today)

@app.route('/recurring/expense/add', methods=['POST'])
@login_required
def add_recurring_expense():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO recurring_expenses
            (source_id, description, category_id, subcategory_id, vendor_id,
             amount, notes, frequency, day_of_month, start_date, is_active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)
    """, (
        request.form.get('source_id') or None,
        request.form.get('description',''),
        request.form.get('category_id') or None,
        request.form.get('subcategory_id') or None,
        request.form.get('vendor_id') or None,
        float(request.form['amount']),
        request.form.get('notes',''),
        request.form['frequency'],
        request.form.get('day_of_month') or None,
        request.form['start_date']
    ))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/expense/delete/<int:rec_id>', methods=['POST'])
@login_required
def delete_recurring_expense(rec_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM recurring_expenses WHERE id = %s', (rec_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/expense/toggle/<int:rec_id>', methods=['POST'])
@login_required
def toggle_recurring_expense(rec_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE recurring_expenses
        SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
        WHERE id = %s
    """, (rec_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/expense/post/<int:rec_id>', methods=['POST'])
@login_required
def post_recurring_expense(rec_id):
    """Manually post a recurring expense as an actual expense for today."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM recurring_expenses WHERE id = %s', (rec_id,))
    rec = cursor.fetchone()
    if rec:
        post_date = request.form.get('post_date', datetime.now().strftime('%Y-%m-%d'))
        cursor.execute("""
            INSERT INTO expenses
                (date, source_id, description, category_id, subcategory_id,
                 vendor_id, amount, notes, recurring_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
        """, (post_date, rec['source_id'], rec['description'], rec['category_id'],
              rec['subcategory_id'], rec['vendor_id'], rec['amount'],
              rec['notes'], rec_id))
        conn.commit()
    cursor.close(); conn.close()
    return redirect(url_for('recurring'))

# ---- Recurring Income ----
@app.route('/recurring/income/add', methods=['POST'])
@login_required
def add_recurring_income():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO recurring_income
            (source_id, description, category_id, amount, notes,
             frequency, day_of_month, start_date, is_active)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)
    """, (
        request.form.get('source_id') or None,
        request.form.get('description',''),
        request.form.get('category_id') or None,
        float(request.form['amount']),
        request.form.get('notes',''),
        request.form['frequency'],
        request.form.get('day_of_month') or None,
        request.form['start_date']
    ))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/income/delete/<int:rec_id>', methods=['POST'])
@login_required
def delete_recurring_income(rec_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM recurring_income WHERE id = %s', (rec_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/income/toggle/<int:rec_id>', methods=['POST'])
@login_required
def toggle_recurring_income(rec_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE recurring_income
        SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END
        WHERE id = %s
    """, (rec_id,))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('recurring'))

@app.route('/recurring/income/post/<int:rec_id>', methods=['POST'])
@login_required
def post_recurring_income(rec_id):
    """Manually post a recurring income as an actual income entry."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM recurring_income WHERE id = %s', (rec_id,))
    rec = cursor.fetchone()
    if rec:
        post_date = request.form.get('post_date', datetime.now().strftime('%Y-%m-%d'))
        cursor.execute("""
            INSERT INTO income
                (date, source_id, description, category_id,
                 amount, notes, recurring_id, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)
        """, (post_date, rec['source_id'], rec['description'],
              rec['category_id'], rec['amount'], rec['notes'], rec_id))
        conn.commit()
    cursor.close(); conn.close()
    return redirect(url_for('recurring'))


@app.route('/manage/categories/edit/<int:category_id>', methods=['POST'])
@login_required
def edit_category(category_id):
    name = request.form['name'].strip()
    color = request.form.get('color', '#6c757d')
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('UPDATE categories SET name = %s, color = %s WHERE id = %s', (name, color, category_id))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_categories'))

@app.route('/manage/subcategories/edit/<int:subcategory_id>', methods=['POST'])
@login_required
def edit_subcategory(subcategory_id):
    name = request.form['name'].strip()
    category_id = request.form['category_id']
    conn = get_db_connection(); cursor = conn.cursor()
    cursor.execute('UPDATE subcategories SET name = %s, category_id = %s WHERE id = %s',
                  (name, category_id, subcategory_id))
    conn.commit(); cursor.close(); conn.close()
    return redirect(url_for('manage_subcategories'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
