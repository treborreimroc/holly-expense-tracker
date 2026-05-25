from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
import bcrypt
from datetime import datetime
from functools import wraps
import os

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
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO expenses (date, source_id, description, category_id,
                                subcategory_id, vendor_id, amount, notes, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
        """, (date_val, source_id, description, category_id, subcategory_id, vendor_id, amount, notes))
        conn.commit(); cursor.close(); conn.close()
        return redirect(url_for('view_expenses'))

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.close(); conn.close()
    return render_template('add_expense.html', sources=sources, categories=categories,
                         subcategories=subcategories, vendors=vendors,
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
        WHERE e.archived = 0 AND (e.is_split = 0 OR e.is_split = 2)
    """
    params = []
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
    cursor.execute('SELECT * FROM categories ORDER BY name'); categories = cursor.fetchall()
    cursor.execute('SELECT * FROM subcategories ORDER BY name'); subcategories = cursor.fetchall()
    cursor.execute('SELECT * FROM vendors ORDER BY name'); vendors = cursor.fetchall()
    cursor.execute('SELECT * FROM sources ORDER BY name'); sources = cursor.fetchall()
    cursor.close(); conn.close()
    filters_active = any([filter_date_from, filter_date_to, filter_category,
                          filter_subcategory, filter_vendor, filter_source, filter_search])
    return render_template('view_expenses.html', expenses=expenses, total=total,
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
        WHERE i.archived = 0
    """
    params = []
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
    cursor.execute('SELECT COUNT(*) as count FROM vendors'); vendors_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM expenses'); expenses_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM income'); income_count = cursor.fetchone()['count']
    cursor.execute('SELECT COUNT(*) as count FROM income_categories'); income_cat_count = cursor.fetchone()['count']
    cursor.close(); conn.close()
    stats = {'sources': sources_count, 'categories': categories_count, 'vendors': vendors_count,
             'expenses': expenses_count, 'income': income_count, 'income_categories': income_cat_count}
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

    cursor.close()
    conn.close()

    return render_template('pnl.html',
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
    import json as json_lib
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
