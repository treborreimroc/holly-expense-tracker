from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify, flash
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

def get_db_connection():
    """Connect to PostgreSQL database"""
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

@app.route('/add-expense', methods=['GET', 'POST'])
@login_required  
def add_expense():
    if request.method == 'POST':
        # Get form data
        date = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
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
        """, (date, source_id, description, category_id, subcategory_id, 
              vendor_id, amount, notes))
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('view_expenses'))
    
    # GET request - show form
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute('SELECT * FROM sources ORDER BY name')
    sources = cursor.fetchall()
    
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM subcategories ORDER BY name')
    subcategories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM vendors ORDER BY name')
    vendors = cursor.fetchall()
    
    cursor.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order')
    tax_rates = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    return render_template('add_expense.html', 
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         tax_rates=tax_rates,
                         today=today)

@app.route('/view-expenses')
@login_required
def view_expenses():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute("""
        SELECT e.*, 
               s.name as source_name,
               c.name as category_name,
               c.color as category_color,
               sc.name as subcategory_name,
               v.name as vendor_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        WHERE e.archived = 0
        ORDER BY e.date DESC, e.created_at DESC
        LIMIT 100
    """)
    expenses = cursor.fetchall()
    
    cursor.execute('SELECT SUM(amount) as total FROM expenses WHERE archived = 0')
    total_result = cursor.fetchone()
    total = total_result['total'] if total_result['total'] else 0
    
    cursor.close()
    conn.close()
    
    return render_template('view_expenses.html', expenses=expenses, total=total)

@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
@login_required
def delete_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM expenses WHERE id = %s', (expense_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('view_expenses'))

@app.route('/manage')
@login_required
def manage():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute('SELECT COUNT(*) as count FROM sources')
    sources_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM categories')
    categories_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM vendors')
    vendors_count = cursor.fetchone()['count']
    
    cursor.execute('SELECT COUNT(*) as count FROM expenses')
    expenses_count = cursor.fetchone()['count']
    
    cursor.close()
    conn.close()
    
    stats = {
        'sources': sources_count,
        'categories': categories_count,
        'vendors': vendors_count,
        'expenses': expenses_count
    }
    
    return render_template('manage.html', stats=stats)


@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST'])
@login_required
def edit_expense(expense_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if request.method == 'POST':
        # Update expense
        date = request.form.get('date')
        amount = float(request.form['amount'])
        source_id = request.form['source_id']
        description = request.form.get('description', '')
        category_id = request.form['category_id']
        subcategory_id = request.form.get('subcategory_id') or None
        vendor_id = request.form.get('vendor_id') or None
        notes = request.form.get('notes', '')
        
        cursor.execute("""
            UPDATE expenses 
            SET date = %s, source_id = %s, description = %s, category_id = %s,
                subcategory_id = %s, vendor_id = %s, amount = %s, notes = %s
            WHERE id = %s
        """, (date, source_id, description, category_id, subcategory_id, 
              vendor_id, amount, notes, expense_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect(url_for('view_expenses'))
    
    # GET - show edit form
    cursor.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,))
    expense = cursor.fetchone()
    
    if not expense:
        cursor.close()
        conn.close()
        return "Expense not found", 404
    
    cursor.execute('SELECT * FROM sources ORDER BY name')
    sources = cursor.fetchall()
    
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM subcategories ORDER BY name')
    subcategories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM vendors ORDER BY name')
    vendors = cursor.fetchall()
    
    cursor.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order')
    tax_rates = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('edit_expense.html',
                         expense=expense,
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         tax_rates=tax_rates)


# ============= SOURCES MANAGEMENT =============
@app.route('/manage/sources')
@login_required
def manage_sources():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM sources ORDER BY name')
    sources = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_sources.html', sources=sources)

@app.route('/manage/sources/add', methods=['POST'])
@login_required
def add_source():
    name = request.form['name']
    source_type = request.form.get('type', '')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO sources (name, type) VALUES (%s, %s)', (name, source_type))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_sources'))

@app.route('/manage/sources/delete/<int:source_id>', methods=['POST'])
@login_required
def delete_source(source_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM sources WHERE id = %s', (source_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_sources'))

# ============= CATEGORIES MANAGEMENT =============
@app.route('/manage/categories')
@login_required
def manage_categories():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_categories.html', categories=categories)

@app.route('/manage/categories/add', methods=['POST'])
@login_required
def add_category():
    name = request.form['name']
    color = request.form.get('color', '#6c757d')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO categories (name, color) VALUES (%s, %s)', (name, color))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_categories'))

@app.route('/manage/categories/delete/<int:category_id>', methods=['POST'])
@login_required
def delete_category(category_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM categories WHERE id = %s', (category_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_categories'))

# ============= VENDORS MANAGEMENT =============
@app.route('/manage/vendors')
@login_required
def manage_vendors():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('SELECT * FROM vendors ORDER BY name')
    vendors = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('manage_vendors.html', vendors=vendors)

@app.route('/manage/vendors/add', methods=['POST'])
@login_required
def add_vendor():
    name = request.form['name']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO vendors (name) VALUES (%s)', (name,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_vendors'))

@app.route('/manage/vendors/delete/<int:vendor_id>', methods=['POST'])
@login_required
def delete_vendor(vendor_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM vendors WHERE id = %s', (vendor_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_vendors'))

# ============= SUBCATEGORIES MANAGEMENT =============
@app.route('/manage/subcategories')
@login_required
def manage_subcategories():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute("""
        SELECT s.*, c.name as category_name 
        FROM subcategories s
        LEFT JOIN categories c ON s.category_id = c.id
        ORDER BY c.name, s.name
    """)
    subcategories = cursor.fetchall()
    
    cursor.execute('SELECT * FROM categories ORDER BY name')
    categories = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('manage_subcategories.html', 
                         subcategories=subcategories,
                         categories=categories)

@app.route('/manage/subcategories/add', methods=['POST'])
@login_required
def add_subcategory():
    name = request.form['name']
    category_id = request.form['category_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO subcategories (name, category_id) VALUES (%s, %s)', 
                  (name, category_id))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_subcategories'))

@app.route('/manage/subcategories/delete/<int:subcategory_id>', methods=['POST'])
@login_required
def delete_subcategory(subcategory_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM subcategories WHERE id = %s', (subcategory_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return redirect(url_for('manage_subcategories'))


# ============= QUICK ADD ROUTES =============
@app.route('/quick-add/source', methods=['POST'])
@login_required
def quick_add_source():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO sources (name, type) VALUES (%s, %s) RETURNING id', 
                      (name, 'Bank Account'))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/category', methods=['POST'])
@login_required
def quick_add_category():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO categories (name, color) VALUES (%s, %s) RETURNING id', 
                      (name, '#6c757d'))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/vendor', methods=['POST'])
@login_required
def quick_add_vendor():
    name = request.form.get('name', '').strip()
    if name:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO vendors (name) VALUES (%s) RETURNING id', (name,))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

@app.route('/quick-add/subcategory', methods=['POST'])
@login_required
def quick_add_subcategory():
    name = request.form.get('name', '').strip()
    category_id = request.form.get('category_id')
    if name and category_id:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO subcategories (name, category_id) VALUES (%s, %s) RETURNING id', 
                      (name, category_id))
        new_id = cursor.fetchone()[0]
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True, 'id': new_id, 'name': name})
    return jsonify({'success': False})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
