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
        WHERE e.archived = 0
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
