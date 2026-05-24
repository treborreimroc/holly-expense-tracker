from flask import Flask, render_template, request, redirect, url_for, session, send_file, jsonify, flash, send_from_directory
import psycopg2
import psycopg2.extras
from urllib.parse import urlparse
import bcrypt
from datetime import datetime, timedelta
from functools import wraps
import os
from io import BytesIO
from reportlab.lib.pagesizes import letter, portrait
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import csv
from collections import defaultdict
import calendar

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# PostgreSQL connection function
def get_db_connection():
    """Connect to PostgreSQL database"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    result = urlparse(database_url)
    
    conn = psycopg2.connect(
        database=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    return conn

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = %s', (username,)).fetchone()
        conn.close()
        
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password_hash']):
            session['user_id'] = user['id']
            session['username'] = user['username']
            
            # Redirect to next page or home
            next_page = request.args.get('next')
            return redirect(next_page if next_page else url_for('add_expense_page'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')



@app.route('/logout')
def logout():
    """Logout"""
    session.clear()
    return redirect(url_for('login'))



@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """Change password page"""
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password != confirm_password:
            return render_template('change_password.html', error='New passwords do not match')
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],)).fetchone()
        
        if not bcrypt.checkpw(current_password.encode('utf-8'), user['password_hash']):
            conn.close()
            return render_template('change_password.html', error='Current password is incorrect')
        
        # Hash new password
        new_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
        conn.execute('UPDATE users SET password_hash = %s WHERE id = %s', 
                    (new_hash, session['user_id']))
        conn.commit()
        conn.close()
        
        return render_template('change_password.html', success='Password changed successfully!')
    
    return render_template('change_password.html')


@login_required


@app.route('/')
def index():
    """Main dashboard - redirect to add expense or login"""
    # Clear session on first access (security: force login every time app opens)
    if 'user_id' not in session:
        session.clear()
        return redirect(url_for('login'))
    return redirect(url_for('add_expense_page'))

@login_required


@app.route('/add-expense')
def add_expense_page():
    """Add expense page - just the entry form"""
    conn = get_db_connection()
    
    # Get data for dropdowns
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    tax_rates = conn.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order').fetchall()
    
    conn.close()
    
    return render_template('add_expense.html',
                         sources=sources,
                         categories=categories,
                         vendors=vendors,
                         tax_rates=tax_rates)

@login_required


@app.route('/view-expenses')
def view_expenses():
    """Expenses page - main expense tracking interface with filtering"""
    from datetime import datetime, timedelta
    
    conn = get_db_connection()
    
    # Get filter parameters from query string
    filter_period = request.args.get('period', 'all')
    filter_source = request.args.get('source', '')
    filter_category = request.args.get('category', '')
    filter_vendor = request.args.get('vendor', '')
    filter_search = request.args.get('search', '')
    filter_subcategory = request.args.get('subcategory', '')
    filter_start_date = request.args.get('start_date', '')
    filter_end_date = request.args.get('end_date', '')
    show_archived = request.args.get('show_archived', 'false') == 'true' 
    
    # Build the WHERE clause based on filters
    where_clauses = []
    params = []
    
    # Date filtering
    today = datetime.now().date()
    if filter_period == 'wtd':  # Week to date (Monday to today)
        start_of_week = today - timedelta(days=today.weekday())
        where_clauses.append('e.date >= %s')
        params.append(start_of_week.isoformat())
    elif filter_period == 'mtd':  # Month to date
        start_of_month = today.replace(day=1)
        where_clauses.append('e.date >= %s')
        params.append(start_of_month.isoformat())
    elif filter_period == 'ytd':  # Year to date
        start_of_year = today.replace(month=1, day=1)
        where_clauses.append('e.date >= %s')
        params.append(start_of_year.isoformat())
    elif filter_period == 'custom' and filter_start_date:
        where_clauses.append('e.date >= %s')
        params.append(filter_start_date)
        if filter_end_date:
            where_clauses.append('e.date <= %s')
            params.append(filter_end_date)
    
    # Source filtering
    if filter_source:
        where_clauses.append('e.source_id = %s')
        params.append(filter_source)
    
    # Category filtering
    if filter_category:
        where_clauses.append('e.category_id = %s')
        params.append(filter_category)
    
    # Vendor filtering
    if filter_vendor:
        where_clauses.append('e.vendor_id = %s')
        params.append(filter_vendor)
    
    # Search filtering (description or notes)
    if filter_search:
        where_clauses.append('(e.description LIKE %s OR e.notes LIKE %s)')
        search_term = f'%{filter_search}%'
        params.extend([search_term, search_term])
    
    # Subcategory filtering
    if filter_subcategory:
        where_clauses.append('e.subcategory_id = %s')
        params.append(filter_subcategory)
    
    # Filter archived expenses unless show_archived is true
    if not show_archived:
        where_clauses.append('e.archived = 0')
    
    # Hide child splits - only show parent and normal transactions
    where_clauses.append('(e.is_split IS NULL OR e.is_split != 2)')
    
    # Hide future recurring expenses (they still show in P&L for forecasting)
    where_clauses.append('(e.recurring_id IS NULL OR e.date <= %s)')
    params.append(today.isoformat())
    
    # Construct the WHERE clause
    where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
    
    # Get filtered expenses
    expenses = conn.execute(f'''
        SELECT 
            e.id,
            e.date,
            e.description,
            e.amount,
            e.notes,
            e.archived,
            e.is_split,
            e.imported_from_mobile,
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
        WHERE {where_sql}
        ORDER BY e.date DESC, e.created_at DESC
    ''', params).fetchall()
    
    # Get data for dropdowns
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    
    # Calculate filtered total
    total_result = conn.execute(f'''
        SELECT SUM(amount) as total, COUNT(*) as count 
        FROM expenses e 
        WHERE {where_sql}
    ''', params).fetchone()
    
    filtered_total = total_result['total'] if total_result['total'] else 0
    filtered_count = total_result['count']
    
    # Calculate overall total for comparison
    overall_result = conn.execute('SELECT SUM(amount) as total FROM expenses').fetchone()
    total_expenses = overall_result['total'] if overall_result['total'] else 0
    
    conn.close()
    
    return render_template('view_expenses.html', 
                         expenses=expenses,
                         sources=sources,
                         categories=categories,
                         vendors=vendors,
                         total_expenses=total_expenses,
                         filtered_total=filtered_total,
                         filtered_count=filtered_count,
                         filter_period=filter_period,
                         filter_source=filter_source,
                         filter_category=filter_category,
                         filter_vendor=filter_vendor,
                         filter_search=filter_search,
                         filter_subcategory=filter_subcategory,
                         filter_start_date=filter_start_date,
                         filter_end_date=filter_end_date)

@login_required


@app.route('/api/subcategories/<int:category_id>')
def get_subcategories(category_id):
    """API endpoint to get subcategories for a given category"""
    conn = get_db_connection()
    subcategories = conn.execute(
        'SELECT * FROM subcategories WHERE category_id = %s ORDER BY name',
        (category_id,)
    ).fetchall()
    conn.close()
    
    return jsonify([{
        'id': sub['id'],
        'name': sub['name']
    } for sub in subcategories])

@login_required

# ============================================================================
# QUICK ADD API ENDPOINTS
# ============================================================================



@app.route('/api/quick-add/source', methods=['POST'])
def quick_add_source():
    """Quick add a source from expense entry"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        source_type = data.get('type', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        
        conn = get_db_connection()
        
        # Check if exists
        existing = conn.execute('SELECT id FROM sources WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': f'Source "{name}" already exists'})
        
        # Insert
        cursor = conn.execute('INSERT INTO sources (name, type) VALUES (%s, %s)', 
                             (name, source_type if source_type else None))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'id': new_id, 'name': name})
    except Exception as e:
        print(f'Error in quick_add_source: {e}')
        return jsonify({'success': False, 'error': 'Failed to add source'})



@app.route('/api/quick-add/category', methods=['POST'])
def quick_add_category():
    """Quick add a category from expense entry"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        color = data.get('color', '#3498db')
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        
        conn = get_db_connection()
        
        # Check if exists
        existing = conn.execute('SELECT id FROM categories WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': f'Category "{name}" already exists'})
        
        # Insert
        cursor = conn.execute('INSERT INTO categories (name, color) VALUES (%s, %s)', (name, color))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'id': new_id, 'name': name})
    except Exception as e:
        print(f'Error in quick_add_category: {e}')
        return jsonify({'success': False, 'error': 'Failed to add category'})



@app.route('/api/quick-add/subcategory', methods=['POST'])
def quick_add_subcategory():
    """Quick add a subcategory from expense entry"""
    try:
        data = request.get_json()
        category_id = data.get('category_id')
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        
        if not category_id:
            return jsonify({'success': False, 'error': 'Category is required'})
        
        conn = get_db_connection()
        
        # Check if exists in this category
        existing = conn.execute(
            'SELECT id FROM subcategories WHERE name = %s AND category_id = %s', 
            (name, category_id)
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': f'Subcategory "{name}" already exists in this category'})
        
        # Insert
        cursor = conn.execute('INSERT INTO subcategories (category_id, name) VALUES (%s, %s)', 
                             (category_id, name))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'id': new_id, 'name': name})
    except Exception as e:
        print(f'Error in quick_add_subcategory: {e}')
        return jsonify({'success': False, 'error': 'Failed to add subcategory'})



@app.route('/api/quick-add/vendor', methods=['POST'])
def quick_add_vendor():
    """Quick add a vendor from expense entry"""
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        
        if not name:
            return jsonify({'success': False, 'error': 'Name is required'})
        
        conn = get_db_connection()
        
        # Check if exists
        existing = conn.execute('SELECT id FROM vendors WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return jsonify({'success': False, 'error': f'Vendor "{name}" already exists'})
        
        # Insert
        cursor = conn.execute('INSERT INTO vendors (name) VALUES (%s)', (name,))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'id': new_id, 'name': name})
    except Exception as e:
        print(f'Error in quick_add_vendor: {e}')
        return jsonify({'success': False, 'error': 'Failed to add vendor'})



@app.route('/expenses/add', methods=['POST'])
def add_expense():
    """Add a new expense"""
    try:
        date = request.form['date']
        source_id = request.form['source_id']
        description = request.form.get('description', '')
        category_id = request.form['category_id']
        subcategory_id = request.form.get('subcategory_id') or None
        vendor_id = request.form.get('vendor_id') or None
        amount = float(request.form['amount'])
        notes = request.form.get('notes', '')
        is_recurring = request.form.get('is_recurring') == 'on'
        recurring_frequency = request.form.get('recurring_frequency', '')
        recurring_day_of_week = request.form.get('recurring_day_of_week', type=int)
        recurring_day_of_month = request.form.get('recurring_day_of_month', type=int)
        recurring_end_date = request.form.get('recurring_end_date') or None
        
        conn = get_db_connection()
        recurring_id = None
        
        if is_recurring and recurring_frequency:
            cursor = conn.execute('''
                INSERT INTO recurring_expenses (source_id, description, category_id,
                    subcategory_id, vendor_id, amount, notes, frequency,
                    day_of_week, day_of_month, start_date, end_date, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (source_id, description, category_id, subcategory_id,
                  vendor_id, amount, notes, recurring_frequency,
                  recurring_day_of_week, recurring_day_of_month,
                  date, recurring_end_date))
            recurring_id = cursor.lastrowid
            print(f"Created recurring expense ID: {recurring_id}, frequency: {recurring_frequency}")
            generate_recurring_expenses(conn, recurring_id)
        
        # Handle receipt upload
        receipt_path = None
        print(f"DEBUG: request.files = {request.files}")
        if 'receipt' in request.files:
            file = request.files['receipt']
            print(f"DEBUG: file = {file}, filename = {file.filename}")
            if file and file.filename:
                from werkzeug.utils import secure_filename
                ext = os.path.splitext(secure_filename(file.filename))[1]
                safe_desc = "".join(c for c in description[:15] if c.isalnum() or c in (' ', '-', '_'))
                filename = f"{date}_{safe_desc}${amount}{ext}"
                filepath = os.path.join('receipts', filename)
                file.save(filepath)
                receipt_path = filepath
                print(f"Saved receipt: {filepath}")
        
        # Get reimbursable flags
        is_reimbursable = 1 if request.form.get('is_reimbursable') else 0
        is_reimbursed = 0  # Always 0 on new expense
        
        conn.execute('''
            INSERT INTO expenses (date, source_id, description, category_id, 
                                subcategory_id, vendor_id, amount, notes, recurring_id, receipt_path,
                                is_reimbursable, is_reimbursed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (date, source_id, description, category_id, subcategory_id, 
              vendor_id, amount, notes, recurring_id, receipt_path, is_reimbursable, is_reimbursed))
        
        # Auto-update debt balance if source matches a credit card debt
        # Get source name
        source = conn.execute('SELECT name FROM sources WHERE id = %s', (source_id,)).fetchone()
        if source:
            source_name = source['name']
            
            # Check if there's an active debt with matching name (case-insensitive)
            debt = conn.execute(
                'SELECT id, current_balance FROM debts WHERE LOWER(name) = LOWER(%s) AND is_active = 1',
                (source_name,)
            ).fetchone()
            
            if debt:
                # Update debt balance - increase by expense amount
                new_balance = debt['current_balance'] + amount
                conn.execute(
                    'UPDATE debts SET current_balance = %s WHERE id = %s',
                    (new_balance, debt['id'])
                )
                print(f"Auto-updated debt '{source_name}': ${debt['current_balance']:.2f} → ${new_balance:.2f} (+${amount:.2f})")
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('view_expenses'))
    except Exception as e:
        print(f"Error adding expense: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('add_expense_page'))

@login_required


@app.route('/expenses/delete/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    """Delete an expense"""
    conn = get_db_connection()
    
    # Get expense details before deleting to check if it affects debt
    expense = conn.execute('''
        SELECT e.amount, s.name as source_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        WHERE e.id = %s
    ''', (expense_id,)).fetchone()
    
    if expense:
        # Check if source matches an active debt
        debt = conn.execute(
            'SELECT id, current_balance FROM debts WHERE LOWER(name) = LOWER(?) AND is_active = 1',
            (expense['source_name'],)
        ).fetchone()
        
        if debt:
            # Decrease debt balance since we're removing the charge
            new_balance = debt['current_balance'] - expense['amount']
            conn.execute(
                'UPDATE debts SET current_balance = %s WHERE id = %s',
                (new_balance, debt['id'])
            )
            print(f"Auto-updated debt '{expense['source_name']}': ${debt['current_balance']:.2f} → ${new_balance:.2f} (-${expense['amount']:.2f})")
    
    # Get expense to check for receipt file
    expense_to_delete = conn.execute('SELECT receipt_path FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    
    # Delete receipt file if exists
    if expense_to_delete and expense_to_delete['receipt_path']:
        if os.path.exists(expense_to_delete['receipt_path']):
            os.remove(expense_to_delete['receipt_path'])
            print(f"Deleted receipt file: {expense_to_delete['receipt_path']}")
    
    # Check if this is a parent of split transactions
    is_parent = conn.execute('SELECT is_split FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    
    if is_parent and is_parent['is_split'] == 1:
        # Delete all children first
        conn.execute('DELETE FROM expenses WHERE parent_transaction_id = %s', (expense_id,))
        print(f"Deleted child splits for parent {expense_id}")
    
    # Delete the expense itself
    conn.execute('DELETE FROM expenses WHERE id = %s', (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_expenses'))

@login_required


@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST'])
def edit_expense(expense_id):
    """Edit an existing expense"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        try:
            # Fetch current expense for receipt_path and is_split
            current_expense = conn.execute("SELECT receipt_path, is_split FROM expenses WHERE id = %s", (expense_id,)).fetchone()

            date = request.form['date']
            source_id = request.form['source_id']
            description = request.form.get('description', '')
            category_id = request.form['category_id']
            subcategory_id = request.form.get('subcategory_id') or None
            vendor_id = request.form.get('vendor_id') or None
            amount = float(request.form['amount'])
            notes = request.form.get('notes', '')
            
            # Get taxable flag and tax data
            # Get taxable flag and tax data
            taxable = 1 if request.form.get('taxable') else 0
            tax_rate_id = request.form.get('tax_rate_id') or None
            subtotal = request.form.get('subtotal') or amount
            tax_amount = request.form.get('tax_amount') or 0
            
            # If not taxable, clear tax data
            if not taxable:
                tax_rate_id = None
                subtotal = amount
                tax_amount = 0
            
            # Handle receipt upload
            receipt_path = current_expense['receipt_path'] if current_expense else None
            if 'receipt' in request.files:
                file = request.files['receipt']
                if file and file.filename:
                    from werkzeug.utils import secure_filename
                    # Delete old receipt if exists
                    if receipt_path and os.path.exists(receipt_path):
                        os.remove(receipt_path)
                    
                    ext = os.path.splitext(secure_filename(file.filename))[1]
                    safe_desc = "".join(c for c in description[:15] if c.isalnum() or c in (' ', '-', '_'))
                    filename = f"{date}_{safe_desc}${amount}{ext}"
                    filepath = os.path.join('receipts', filename)
                    file.save(filepath)
                    receipt_path = filepath
                    print(f"Updated receipt: {filepath}")
            
            # Get reimbursable flags
            is_reimbursable = 1 if request.form.get('is_reimbursable') else 0
            is_reimbursed = 1 if request.form.get('is_reimbursed') else 0
            
            # If not reimbursable, clear reimbursed flag
            if not is_reimbursable:
                is_reimbursed = 0
            
            conn.execute('''
                UPDATE expenses 
                SET date=%s, source_id=%s, description=%s, category_id=%s, 
                    subcategory_id=%s, vendor_id=%s, amount=%s, notes=%s,
                    taxable=%s, tax_rate_id=%s, subtotal=%s, tax_amount=%s, receipt_path=%s,
                    is_reimbursable=%s, is_reimbursed=%s
                WHERE id=%s
            ''', (date, source_id, description, category_id, subcategory_id,
                  vendor_id, amount, notes, taxable, tax_rate_id, subtotal, tax_amount, receipt_path,
                  is_reimbursable, is_reimbursed, expense_id))
            
            # If this is a split parent, update all children dates too
            if current_expense and current_expense['is_split'] == 1:
                conn.execute('''UPDATE expenses SET date = %s WHERE parent_transaction_id = %s''',
                           (date, expense_id))
                print(f"DEBUG: Updated child dates for parent {expense_id}")
            
            conn.commit()
            conn.close()
            return redirect(url_for('view_expenses'))
        except Exception as e:
            print(f"Error editing expense: {e}")
            conn.close()
            return redirect(url_for('view_expenses'))
    
    # GET request - show edit form
    expense = conn.execute(
        'SELECT * FROM expenses WHERE id = %s', 
        (expense_id,)
    ).fetchone()
    
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    subcategories = conn.execute(
        'SELECT * FROM subcategories WHERE category_id = %s ORDER BY name',
        (expense['category_id'],)
    ).fetchall()
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    
    # Get tax rates
    tax_rates = conn.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order').fetchall()
    
    conn.close()
    
    return render_template('edit_expense.html',
                         expense=expense,
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         tax_rates=tax_rates)

@login_required


@app.route('/manage')
def manage():
    """Manage categories, subcategories, vendors, and sources"""
    conn = get_db_connection()
    
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    # Get subcategories with category names
    subcategories = conn.execute('''
        SELECT sc.*, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    
    # Get income categories
    income_categories = conn.execute('SELECT * FROM income_categories ORDER BY name').fetchall()
    
    conn.close()
    
    return render_template('manage.html',
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         income_categories=income_categories)

@login_required


@app.route('/manage/sources')
def manage_sources():
    """Manage sources page"""
    conn = get_db_connection()
    
    # Get sources with expense count
    sources = conn.execute('''
        SELECT s.*, COUNT(e.id) as expense_count
        FROM sources s
        LEFT JOIN expenses e ON s.id = e.source_id
        GROUP BY s.id
        ORDER BY s.name
    ''').fetchall()
    
    conn.close()
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    return render_template('manage_sources.html',
                         sources=sources,
                         success=success,
                         error=error)

@login_required


@app.route('/manage/sources/add', methods=['POST'])
def add_source():
    """Add a new source"""
    try:
        name = request.form['name'].strip()
        source_type = request.form.get('type', '').strip()
        
        if not name:
            return redirect(url_for('manage_sources', error='Source name is required'))
        
        conn = get_db_connection()
        
        # Check if source already exists
        existing = conn.execute('SELECT id FROM sources WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_sources', error=f'Source "{name}" already exists'))
        
        # Insert new source
        conn.execute('INSERT INTO sources (name, type) VALUES (%s, %s)', 
                    (name, source_type if source_type else None))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_sources', success=f'Source "{name}" added successfully!'))
    except Exception as e:
        print(f"Error adding source: {e}")
        return redirect(url_for('manage_sources', error='Failed to add source'))

@login_required


@app.route('/manage/sources/edit', methods=['POST'])
def edit_source():
    """Edit an existing source"""
    try:
        source_id = request.form['source_id']
        name = request.form['name'].strip()
        source_type = request.form.get('type', '').strip()
        
        if not name:
            return redirect(url_for('manage_sources', error='Source name is required'))
        
        conn = get_db_connection()
        
        # Check if another source has this name
        existing = conn.execute(
            'SELECT id FROM sources WHERE name = %s AND id != %s', 
            (name, source_id)
        ).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_sources', error=f'Another source named "{name}" already exists'))
        
        # Update source
        conn.execute('UPDATE sources SET name = %s, type = %s WHERE id = %s',
                    (name, source_type if source_type else None, source_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_sources', success=f'Source "{name}" updated successfully!'))
    except Exception as e:
        print(f"Error editing source: {e}")
        return redirect(url_for('manage_sources', error='Failed to update source'))

@login_required


@app.route('/manage/sources/delete/<int:source_id>', methods=['POST'])
def delete_source(source_id):
    """Delete a source"""
    try:
        conn = get_db_connection()
        
        # Get source name and check if it's being used
        source = conn.execute(
            'SELECT name FROM sources WHERE id = %s', 
            (source_id,)
        ).fetchone()
        
        if not source:
            conn.close()
            return redirect(url_for('manage_sources', error='Source not found'))
        
        expense_count = conn.execute(
            'SELECT COUNT(*) as count FROM expenses WHERE source_id = %s',
            (source_id,)
        ).fetchone()['count']
        
        if expense_count > 0:
            conn.close()
            return redirect(url_for('manage_sources', 
                error=f'Cannot delete "{source["name"]}" - it is being used by {expense_count} expense(s). Reassign or delete those expenses first.'))
        
        # Delete the source
        conn.execute('DELETE FROM sources WHERE id = %s', (source_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_sources', success=f'Source "{source["name"]}" deleted successfully!'))
    except Exception as e:
        print(f"Error deleting source: {e}")
        return redirect(url_for('manage_sources', error='Failed to delete source'))

@login_required


@app.route('/manage/categories')
def manage_categories():
    """Manage categories page"""
    conn = get_db_connection()
    
    # Get categories with subcategory and expense counts
    categories = conn.execute('''
        SELECT c.*, 
               COUNT(DISTINCT sc.id) as subcategory_count,
               COUNT(DISTINCT e.id) as expense_count
        FROM categories c
        LEFT JOIN subcategories sc ON c.id = sc.category_id
        LEFT JOIN expenses e ON c.id = e.category_id
        GROUP BY c.id
        ORDER BY c.name
    ''').fetchall()
    
    conn.close()
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    return render_template('manage_categories.html',
                         categories=categories,
                         success=success,
                         error=error)

@login_required


@app.route('/manage/categories/add', methods=['POST'])
def add_category():
    """Add a new category"""
    try:
        name = request.form['name'].strip()
        color = request.form['color'].strip()
        
        if not name:
            return redirect(url_for('manage_categories', error='Category name is required'))
        
        if not color:
            color = '#3498db'  # Default blue
        
        conn = get_db_connection()
        
        # Check if category already exists
        existing = conn.execute('SELECT id FROM categories WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_categories', error=f'Category "{name}" already exists'))
        
        # Insert new category
        conn.execute('INSERT INTO categories (name, color) VALUES (%s, %s)', (name, color))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_categories', success=f'Category "{name}" added successfully!'))
    except Exception as e:
        print(f"Error adding category: {e}")
        return redirect(url_for('manage_categories', error='Failed to add category'))

@login_required


@app.route('/manage/categories/edit', methods=['POST'])
def edit_category():
    """Edit an existing category"""
    try:
        category_id = request.form['category_id']
        name = request.form['name'].strip()
        color = request.form['color'].strip()
        
        if not name:
            return redirect(url_for('manage_categories', error='Category name is required'))
        
        if not color:
            color = '#3498db'
        
        conn = get_db_connection()
        
        # Check if another category has this name
        existing = conn.execute(
            'SELECT id FROM categories WHERE name = %s AND id != %s', 
            (name, category_id)
        ).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_categories', error=f'Another category named "{name}" already exists'))
        
        # Update category
        conn.execute('UPDATE categories SET name = %s, color = %s WHERE id = %s',
                    (name, color, category_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_categories', success=f'Category "{name}" updated successfully!'))
    except Exception as e:
        print(f"Error editing category: {e}")
        return redirect(url_for('manage_categories', error='Failed to update category'))

@login_required


@app.route('/manage/categories/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):
    """Delete a category"""
    try:
        conn = get_db_connection()
        
        # Get category name and check if it's being used
        category = conn.execute(
            'SELECT name FROM categories WHERE id = %s', 
            (category_id,)
        ).fetchone()
        
        if not category:
            conn.close()
            return redirect(url_for('manage_categories', error='Category not found'))
        
        # Check for subcategories
        subcategory_count = conn.execute(
            'SELECT COUNT(*) as count FROM subcategories WHERE category_id = %s',
            (category_id,)
        ).fetchone()['count']
        
        # Check for expenses
        expense_count = conn.execute(
            'SELECT COUNT(*) as count FROM expenses WHERE category_id = %s',
            (category_id,)
        ).fetchone()['count']
        
        if subcategory_count > 0 or expense_count > 0:
            error_msg = f'Cannot delete "{category["name"]}" - it is being used by '
            parts = []
            if subcategory_count > 0:
                parts.append(f'{subcategory_count} subcategor{"ies" if subcategory_count != 1 else "y"}')
            if expense_count > 0:
                parts.append(f'{expense_count} expense{"s" if expense_count != 1 else ""}')
            error_msg += ' and '.join(parts) + '. Reassign or delete those items first.'
            conn.close()
            return redirect(url_for('manage_categories', error=error_msg))
        
        # Delete the category
        conn.execute('DELETE FROM categories WHERE id = %s', (category_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_categories', success=f'Category "{category["name"]}" deleted successfully!'))
    except Exception as e:
        print(f"Error deleting category: {e}")
        return redirect(url_for('manage_categories', error='Failed to delete category'))

@login_required


@app.route('/manage/vendors')
def manage_vendors():
    """Manage vendors page"""
    conn = get_db_connection()
    
    # Get vendors with expense count and category info
    vendors = conn.execute('''
        SELECT v.*, 
               c.name as category_name,
               c.color as category_color,
               COUNT(e.id) as expense_count
        FROM vendors v
        LEFT JOIN categories c ON v.default_category_id = c.id
        LEFT JOIN expenses e ON v.id = e.vendor_id
        GROUP BY v.id
        ORDER BY v.name
    ''').fetchall()
    
    # Get categories for the dropdown
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    conn.close()
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    return render_template('manage_vendors.html',
                         vendors=vendors,
                         categories=categories,
                         success=success,
                         error=error)

@login_required


@app.route('/manage/vendors/add', methods=['POST'])
def add_vendor():
    """Add a new vendor"""
    try:
        name = request.form['name'].strip()
        default_category_id = request.form.get('default_category_id')
        
        if not name:
            return redirect(url_for('manage_vendors', error='Vendor name is required'))
        
        # Convert empty string to None
        if not default_category_id:
            default_category_id = None
        
        conn = get_db_connection()
        
        # Check if vendor already exists
        existing = conn.execute('SELECT id FROM vendors WHERE name = %s', (name,)).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_vendors', error=f'Vendor "{name}" already exists'))
        
        # Insert new vendor
        conn.execute('INSERT INTO vendors (name, default_category_id) VALUES (%s, %s)', 
                    (name, default_category_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_vendors', success=f'Vendor "{name}" added successfully!'))
    except Exception as e:
        print(f"Error adding vendor: {e}")
        return redirect(url_for('manage_vendors', error='Failed to add vendor'))

@login_required


@app.route('/manage/vendors/edit', methods=['POST'])
def edit_vendor():
    """Edit an existing vendor"""
    try:
        vendor_id = request.form['vendor_id']
        name = request.form['name'].strip()
        default_category_id = request.form.get('default_category_id')
        
        if not name:
            return redirect(url_for('manage_vendors', error='Vendor name is required'))
        
        # Convert empty string to None
        if not default_category_id:
            default_category_id = None
        
        conn = get_db_connection()
        
        # Check if another vendor has this name
        existing = conn.execute(
            'SELECT id FROM vendors WHERE name = %s AND id != %s', 
            (name, vendor_id)
        ).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('manage_vendors', error=f'Another vendor named "{name}" already exists'))
        
        # Update vendor
        conn.execute('UPDATE vendors SET name = %s, default_category_id = %s WHERE id = %s',
                    (name, default_category_id, vendor_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_vendors', success=f'Vendor "{name}" updated successfully!'))
    except Exception as e:
        print(f"Error editing vendor: {e}")
        return redirect(url_for('manage_vendors', error='Failed to update vendor'))

@login_required


@app.route('/manage/vendors/delete/<int:vendor_id>', methods=['POST'])
def delete_vendor(vendor_id):
    """Delete a vendor"""
    try:
        conn = get_db_connection()
        
        # Get vendor name and check if it's being used
        vendor = conn.execute(
            'SELECT name FROM vendors WHERE id = %s', 
            (vendor_id,)
        ).fetchone()
        
        if not vendor:
            conn.close()
            return redirect(url_for('manage_vendors', error='Vendor not found'))
        
        expense_count = conn.execute(
            'SELECT COUNT(*) as count FROM expenses WHERE vendor_id = %s',
            (vendor_id,)
        ).fetchone()['count']
        
        if expense_count > 0:
            conn.close()
            return redirect(url_for('manage_vendors', 
                error=f'Cannot delete "{vendor["name"]}" - it is being used by {expense_count} expense(s). Reassign or delete those expenses first.'))
        
        # Delete the vendor
        conn.execute('DELETE FROM vendors WHERE id = %s', (vendor_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_vendors', success=f'Vendor "{vendor["name"]}" deleted successfully!'))
    except Exception as e:
        print(f"Error deleting vendor: {e}")
        return redirect(url_for('manage_vendors', error='Failed to delete vendor'))

@login_required


@app.route('/manage/subcategories')
def manage_subcategories():
    """Manage subcategories page"""
    conn = get_db_connection()
    
    # Get all categories for the form dropdown
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    
    # Get subcategories with expense count
    subcategories = conn.execute('''
        SELECT sc.*, 
               COUNT(e.id) as expense_count
        FROM subcategories sc
        LEFT JOIN expenses e ON sc.id = e.subcategory_id
        GROUP BY sc.id
        ORDER BY sc.category_id, sc.name
    ''').fetchall()
    
    conn.close()
    
    success = request.args.get('success')
    error = request.args.get('error')
    
    return render_template('manage_subcategories.html',
                         categories=categories,
                         subcategories=subcategories,
                         success=success,
                         error=error)

@login_required


@app.route('/manage/subcategories/add', methods=['POST'])
def add_subcategory():
    """Add a new subcategory"""
    try:
        category_id = request.form['category_id']
        name = request.form['name'].strip()
        
        if not name:
            return redirect(url_for('manage_subcategories', error='Subcategory name is required'))
        
        if not category_id:
            return redirect(url_for('manage_subcategories', error='Please select a parent category'))
        
        conn = get_db_connection()
        
        # Check if subcategory already exists in this category
        existing = conn.execute(
            'SELECT id FROM subcategories WHERE name = %s AND category_id = %s', 
            (name, category_id)
        ).fetchone()
        if existing:
            # Get category name for error message
            category = conn.execute('SELECT name FROM categories WHERE id = %s', (category_id,)).fetchone()
            conn.close()
            return redirect(url_for('manage_subcategories', 
                error=f'Subcategory "{name}" already exists in {category["name"]}'))
        
        # Insert new subcategory
        conn.execute('INSERT INTO subcategories (category_id, name) VALUES (%s, %s)', 
                    (category_id, name))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_subcategories', success=f'Subcategory "{name}" added successfully!'))
    except Exception as e:
        print(f"Error adding subcategory: {e}")
        return redirect(url_for('manage_subcategories', error='Failed to add subcategory'))

@login_required


@app.route('/manage/subcategories/edit', methods=['POST'])
def edit_subcategory():
    """Edit an existing subcategory"""
    try:
        subcategory_id = request.form['subcategory_id']
        category_id = request.form['category_id']
        name = request.form['name'].strip()
        
        if not name:
            return redirect(url_for('manage_subcategories', error='Subcategory name is required'))
        
        if not category_id:
            return redirect(url_for('manage_subcategories', error='Please select a parent category'))
        
        conn = get_db_connection()
        
        # Check if another subcategory in this category has this name
        existing = conn.execute(
            'SELECT id FROM subcategories WHERE name = %s AND category_id = %s AND id != %s', 
            (name, category_id, subcategory_id)
        ).fetchone()
        if existing:
            category = conn.execute('SELECT name FROM categories WHERE id = %s', (category_id,)).fetchone()
            conn.close()
            return redirect(url_for('manage_subcategories', 
                error=f'Another subcategory named "{name}" already exists in {category["name"]}'))
        
        # Update subcategory
        conn.execute('UPDATE subcategories SET category_id = %s, name = %s WHERE id = %s',
                    (category_id, name, subcategory_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_subcategories', success=f'Subcategory "{name}" updated successfully!'))
    except Exception as e:
        print(f"Error editing subcategory: {e}")
        return redirect(url_for('manage_subcategories', error='Failed to update subcategory'))

@login_required


@app.route('/manage/subcategories/delete/<int:subcategory_id>', methods=['POST'])
def delete_subcategory(subcategory_id):
    """Delete a subcategory"""
    try:
        conn = get_db_connection()
        
        # Get subcategory name and check if it's being used
        subcategory = conn.execute(
            'SELECT name FROM subcategories WHERE id = %s', 
            (subcategory_id,)
        ).fetchone()
        
        if not subcategory:
            conn.close()
            return redirect(url_for('manage_subcategories', error='Subcategory not found'))
        
        expense_count = conn.execute(
            'SELECT COUNT(*) as count FROM expenses WHERE subcategory_id = %s',
            (subcategory_id,)
        ).fetchone()['count']
        
        if expense_count > 0:
            conn.close()
            return redirect(url_for('manage_subcategories', 
                error=f'Cannot delete "{subcategory["name"]}" - it is being used by {expense_count} expense(s). Reassign or delete those expenses first.'))
        
        # Delete the subcategory
        conn.execute('DELETE FROM subcategories WHERE id = %s', (subcategory_id,))
        conn.commit()
        conn.close()
        
        return redirect(url_for('manage_subcategories', success=f'Subcategory "{subcategory["name"]}" deleted successfully!'))
    except Exception as e:
        print(f"Error deleting subcategory: {e}")
        return redirect(url_for('manage_subcategories', error='Failed to delete subcategory'))

# ============================================================================
# DEBT TRACKER ROUTES
# ============================================================================

@login_required


@app.route('/debt-tracker')
def debt_tracker():
    """Debt tracker page - individual debt management"""
    conn = get_db_connection()
    
    # Get all debts
    debts = conn.execute('SELECT * FROM debts WHERE is_active = 1 ORDER BY name').fetchall()
    
    # Get selected debt
    debt_id = request.args.get('debt_id')
    selected_debt = None
    payments = []
    summary = None
    filter_period = request.args.get('period', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    if debt_id:
        selected_debt = conn.execute('SELECT * FROM debts WHERE id = %s', (debt_id,)).fetchone()
        
        if selected_debt:
            # Calculate next due date
            from datetime import datetime, timedelta
            import calendar
            
            if selected_debt['due_day']:
                today = datetime.now().date()
                current_day = today.day
                due_day = selected_debt['due_day']
                
                # If due day hasn't passed this month, it's this month
                if current_day <= due_day:
                    try:
                        next_due = today.replace(day=due_day)
                    except ValueError:
                        # Invalid day for this month (e.g., Feb 31)
                        last_day = calendar.monthrange(today.year, today.month)[1]
                        next_due = today.replace(day=min(due_day, last_day))
                else:
                    # Due day passed, calculate next month
                    if today.month == 12:
                        next_month = today.replace(year=today.year + 1, month=1, day=1)
                    else:
                        next_month = today.replace(month=today.month + 1, day=1)
                    
                    try:
                        next_due = next_month.replace(day=due_day)
                    except ValueError:
                        # Invalid day for next month
                        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
                        next_due = next_month.replace(day=min(due_day, last_day))
                
                selected_debt_dict = dict(selected_debt)
                selected_debt_dict['next_due_date'] = next_due.strftime('%B %d, %Y')
                selected_debt = selected_debt_dict
            
            # Build date filter
            where_clauses = ['debt_id = %s']
            params = [debt_id]
            
            today = datetime.now().date()
            if filter_period == 'wtd':
                start_of_week = today - timedelta(days=today.weekday())
                where_clauses.append('payment_date >= %s')
                params.append(start_of_week.isoformat())
            elif filter_period == 'mtd':
                start_of_month = today.replace(day=1)
                where_clauses.append('payment_date >= %s')
                params.append(start_of_month.isoformat())
            elif filter_period == 'ytd':
                start_of_year = today.replace(month=1, day=1)
                where_clauses.append('payment_date >= %s')
                params.append(start_of_year.isoformat())
            elif filter_period == 'custom' and start_date:
                where_clauses.append('payment_date >= %s')
                params.append(start_date)
                if end_date:
                    where_clauses.append('payment_date <= %s')
                    params.append(end_date)
            
            where_sql = ' AND '.join(where_clauses)
            
            # Get filtered payments
            payments = conn.execute(f'''
                SELECT * FROM debt_payments
                WHERE {where_sql}
                ORDER BY payment_date DESC, created_at DESC
            ''', params).fetchall()
            
            # Calculate summary
            if payments:
                summary_result = conn.execute(f'''
                    SELECT 
                        COUNT(*) as payment_count,
                        SUM(amount_paid) as total_paid,
                        SUM(principal_paid) as principal_paid,
                        SUM(interest_charged) as interest_paid
                    FROM debt_payments
                    WHERE {where_sql}
                ''', params).fetchone()
                
                summary = {
                    'payment_count': summary_result['payment_count'],
                    'total_paid': summary_result['total_paid'] or 0,
                    'principal_paid': summary_result['principal_paid'] or 0,
                    'interest_paid': summary_result['interest_paid'] or 0
                }
    
    conn.close()
    
    return render_template('debt_tracker.html',
                         debts=debts,
                         selected_debt=selected_debt,
                         payments=payments,
                         summary=summary,
                         filter_period=filter_period,
                         start_date=start_date,
                         end_date=end_date)

@login_required


@app.route('/debt-tracker/add-debt', methods=['POST'])
def add_debt():
    """Add a new debt"""
    try:
        name = request.form['name'].strip()
        starting_balance = float(request.form['starting_balance'])
        interest_rate = float(request.form['interest_rate'])
        minimum_payment = float(request.form['minimum_payment'])
        due_day = request.form.get('due_day')
        
        if not name or starting_balance < 0:
            return redirect(url_for('debt_tracker', error='Invalid debt information'))
        
        # Convert empty due_day to None
        if not due_day:
            due_day = None
        
        conn = get_db_connection()
        
        # Check if active debt already exists
        existing = conn.execute('SELECT id FROM debts WHERE name = %s AND is_active = 1', (name,)).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('debt_tracker', error=f'Debt "{name}" already exists'))
        
        # Insert new debt
        cursor = conn.execute('''
            INSERT INTO debts (name, starting_balance, current_balance, interest_rate, minimum_payment, due_day)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (name, starting_balance, starting_balance, interest_rate, minimum_payment, due_day))
        
        new_debt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return redirect(url_for('debt_tracker', debt_id=new_debt_id))
    except Exception as e:
        print(f"Error adding debt: {e}")
        return redirect(url_for('debt_tracker', error='Failed to add debt'))

@login_required


@app.route('/debt-tracker/edit-debt', methods=['POST'])
def edit_debt():
    """Edit an existing debt"""
    try:
        debt_id = request.form['debt_id']
        name = request.form['name'].strip()
        starting_balance = float(request.form['starting_balance'])
        interest_rate = float(request.form['interest_rate'])
        minimum_payment = float(request.form['minimum_payment'])
        due_day = request.form.get('due_day')
        
        if not name or starting_balance < 0:
            return redirect(url_for('debt_tracker', debt_id=debt_id, error='Invalid debt information'))
        
        if not due_day:
            due_day = None
        
        conn = get_db_connection()
        
        # Check if another debt has this name
        existing = conn.execute(
            'SELECT id FROM debts WHERE name = %s AND id != %s',
            (name, debt_id)
        ).fetchone()
        if existing:
            conn.close()
            return redirect(url_for('debt_tracker', debt_id=debt_id, error=f'Another debt named "{name}" already exists'))
        
        # Update debt
        conn.execute('''
            UPDATE debts 
            SET name = %s, 
                starting_balance = %s, 
                current_balance = %s,
                interest_rate = %s, 
                minimum_payment = %s, 
                due_day = %s
            WHERE id = %s
        ''', (name, starting_balance, starting_balance, interest_rate, minimum_payment, due_day, debt_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('debt_tracker', debt_id=debt_id))
    except Exception as e:
        print(f"Error editing debt: {e}")
        return redirect(url_for('debt_tracker', error='Failed to update debt'))

@login_required


@app.route('/debt-tracker/add-payment', methods=['POST'])
def add_payment():
    """Add a payment to a debt"""
    try:
        debt_id = request.form['debt_id']
        payment_date = request.form['payment_date']
        amount_paid = float(request.form['amount_paid'])
        interest_charged = float(request.form['interest_charged'])
        notes = request.form.get('notes', '')
        
        if amount_paid <= 0:
            return redirect(url_for('debt_tracker', debt_id=debt_id, error='Payment amount must be greater than 0'))
        
        conn = get_db_connection()
        
        # Get current debt balance
        debt = conn.execute('SELECT current_balance FROM debts WHERE id = %s', (debt_id,)).fetchone()
        if not debt:
            conn.close()
            return redirect(url_for('debt_tracker', error='Debt not found'))
        
        current_balance = debt['current_balance']
        
        # Calculate principal and new balance
        principal_paid = amount_paid - interest_charged
        new_balance = current_balance + interest_charged - amount_paid
        
        # Ensure balance doesn't go negative
        if new_balance < 0:
            new_balance = 0
        
        # Insert payment
        conn.execute('''
            INSERT INTO debt_payments (debt_id, payment_date, amount_paid, interest_charged, principal_paid, balance_after, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (debt_id, payment_date, amount_paid, interest_charged, principal_paid, new_balance, notes))
        
        # Update debt current_balance
        conn.execute('UPDATE debts SET current_balance = %s WHERE id = %s', (new_balance, debt_id))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('debt_tracker', debt_id=debt_id))
    except Exception as e:
        print(f"Error adding payment: {e}")
        return redirect(url_for('debt_tracker', error='Failed to add payment'))

@login_required


@app.route('/debt-tracker/edit-payment', methods=['POST'])
def edit_payment():
    """Edit an existing payment"""
    try:
        payment_id = request.form['payment_id']
        payment_date = request.form['payment_date']
        amount_paid = float(request.form['amount_paid'])
        interest_charged = float(request.form['interest_charged'])
        notes = request.form.get('notes', '')
        
        if amount_paid <= 0:
            return redirect(url_for('debt_tracker', error='Payment amount must be greater than 0'))
        
        conn = get_db_connection()
        
        # Get the payment and debt info
        payment = conn.execute('SELECT debt_id, balance_after FROM debt_payments WHERE id = %s', (payment_id,)).fetchone()
        if not payment:
            conn.close()
            return redirect(url_for('debt_tracker', error='Payment not found'))
        
        debt_id = payment['debt_id']
        old_balance_after = payment['balance_after']
        
        # Get balance before this payment
        previous_payment = conn.execute('''
            SELECT balance_after FROM debt_payments
            WHERE debt_id = %s AND payment_date < %s
            ORDER BY payment_date DESC, created_at DESC
            LIMIT 1
        ''', (debt_id, payment_date)).fetchone()
        
        if previous_payment:
            balance_before = previous_payment['balance_after']
        else:
            # This is the first payment, use starting balance
            debt = conn.execute('SELECT starting_balance FROM debts WHERE id = %s', (debt_id,)).fetchone()
            balance_before = debt['starting_balance']
        
        # Calculate new values
        principal_paid = amount_paid - interest_charged
        new_balance_after = balance_before + interest_charged - amount_paid
        
        if new_balance_after < 0:
            new_balance_after = 0
        
        # Update payment
        conn.execute('''
            UPDATE debt_payments
            SET payment_date = %s, amount_paid = %s, interest_charged = %s, principal_paid = %s, balance_after = %s, notes = %s
            WHERE id = %s
        ''', (payment_date, amount_paid, interest_charged, principal_paid, new_balance_after, notes, payment_id))
        
        # Update debt current_balance (if this was the most recent payment)
        latest_payment = conn.execute('''
            SELECT id, balance_after FROM debt_payments
            WHERE debt_id = %s
            ORDER BY payment_date DESC, created_at DESC
            LIMIT 1
        ''', (debt_id,)).fetchone()
        
        if latest_payment['id'] == int(payment_id):
            conn.execute('UPDATE debts SET current_balance = %s WHERE id = %s', (new_balance_after, debt_id))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('debt_tracker', debt_id=debt_id))
    except Exception as e:
        print(f"Error editing payment: {e}")
        return redirect(url_for('debt_tracker', error='Failed to update payment'))

@login_required


@app.route('/debt-tracker/delete-payment/<int:payment_id>', methods=['POST'])
def delete_payment(payment_id):
    """Delete a payment"""
    try:
        conn = get_db_connection()
        
        # Get payment info
        payment = conn.execute('SELECT debt_id FROM debt_payments WHERE id = %s', (payment_id,)).fetchone()
        if not payment:
            conn.close()
            return redirect(url_for('debt_tracker', error='Payment not found'))
        
        debt_id = payment['debt_id']
        
        # Delete payment
        conn.execute('DELETE FROM debt_payments WHERE id = %s', (payment_id,))
        
        # Recalculate current balance from most recent payment
        latest_payment = conn.execute('''
            SELECT balance_after FROM debt_payments
            WHERE debt_id = %s
            ORDER BY payment_date DESC, created_at DESC
            LIMIT 1
        ''', (debt_id,)).fetchone()
        
        if latest_payment:
            new_balance = latest_payment['balance_after']
        else:
            # No more payments, reset to starting balance
            debt = conn.execute('SELECT starting_balance FROM debts WHERE id = %s', (debt_id,)).fetchone()
            new_balance = debt['starting_balance']
        
        conn.execute('UPDATE debts SET current_balance = %s WHERE id = %s', (new_balance, debt_id))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('debt_tracker', debt_id=debt_id))
    except Exception as e:
        print(f"Error deleting payment: {e}")
        return redirect(url_for('debt_tracker', error='Failed to delete payment'))

@login_required


@app.route('/debt-payoff')
def debt_payoff():
    """Debt payoff strategy comparison page"""
    conn = get_db_connection()
    
    # Get all active debts
    all_debts = conn.execute('''
        SELECT * FROM debts 
        WHERE is_active = 1 
        ORDER BY current_balance ASC
    ''').fetchall()
    
    conn.close()
    
    if not all_debts:
        return render_template('debt_payoff.html', 
                             included_debts=[], 
                             excluded_debts=[],
                             strategies=None,
                             excluded_schedules=None)
    
    # Split debts into included and excluded
    included_debts = [d for d in all_debts if d['include_in_strategy']]
    excluded_debts = [d for d in all_debts if not d['include_in_strategy']]
    
    # Get extra payment amount from query string
    extra_payment = float(request.args.get('extra_payment', 0))
    
    # Calculate strategies for included debts only
    strategies = None
    if included_debts:
        strategies = calculate_payoff_strategies(included_debts, extra_payment)
    
    # Calculate fixed payment schedules for excluded debts
    excluded_schedules = None
    if excluded_debts:
        excluded_schedules = calculate_fixed_payment_schedules(excluded_debts)
    
    return render_template('debt_payoff.html', 
                         included_debts=included_debts,
                         excluded_debts=excluded_debts,
                         strategies=strategies,
                         excluded_schedules=excluded_schedules,
                         extra_payment=extra_payment)

def calculate_payoff_strategies(debts, extra_payment=0):
    """Calculate snowball and avalanche payoff strategies"""
    
    # Convert to list of dicts for easier manipulation
    debt_list = []
    total_debt = 0
    total_min_payment = 0
    
    for debt in debts:
        debt_dict = {
            'id': debt['id'],
            'name': debt['name'],
            'balance': debt['current_balance'],
            'interest_rate': debt['interest_rate'],
            'min_payment': debt['minimum_payment']
        }
        debt_list.append(debt_dict)
        total_debt += debt['current_balance']
        total_min_payment += debt['minimum_payment']
    
    # Calculate average interest rate (weighted by balance)
    if total_debt > 0:
        avg_interest = sum(d['balance'] * d['interest_rate'] for d in debt_list) / total_debt
    else:
        avg_interest = 0
    
    # Snowball: smallest balance first
    snowball_debts = sorted(debt_list, key=lambda x: x['balance'])
    snowball_result = calculate_payoff_timeline(snowball_debts, extra_payment)
    
    # Avalanche: highest interest first
    avalanche_debts = sorted(debt_list, key=lambda x: x['interest_rate'], reverse=True)
    avalanche_result = calculate_payoff_timeline(avalanche_debts, extra_payment)
    
    # Calculate interest saved
    interest_saved = snowball_result['total_interest'] - avalanche_result['total_interest']
    months_saved = snowball_result['months_to_payoff'] - avalanche_result['months_to_payoff']
    
    return {
        'total_debt': total_debt,
        'total_min_payment': total_min_payment,
        'avg_interest': avg_interest,
        'snowball': snowball_result,
        'avalanche': avalanche_result,
        'interest_saved': interest_saved,
        'months_saved': months_saved,
        'extra_payment': extra_payment
    }

def calculate_payoff_timeline(debts, extra_payment):
    """Calculate payoff timeline for a given debt order with monthly breakdown"""
    # Make a copy to avoid modifying original
    debts = [d.copy() for d in debts]
    
    total_interest = 0
    months = 0
    max_months = 600  # 50 years - safety limit
    
    payoff_order = []
    monthly_breakdown = []
    available_extra = extra_payment  # Track extra payment (grows as debts pay off)
    
    while any(d['balance'] > 0 for d in debts) and months < max_months:
        months += 1
        
        # Track this month's data
        month_data = {
            'month': months,
            'debts': []
        }
        
        # Step 1: Add interest to all active debts and track it
        for debt in debts:
            if debt['balance'] > 0:
                monthly_interest = debt['balance'] * (debt['interest_rate'] / 100 / 12)
                debt['balance'] += monthly_interest
                total_interest += monthly_interest
                debt['interest_this_month'] = monthly_interest
            else:
                debt['interest_this_month'] = 0
        
        # Step 2: Pay MINIMUM on ALL active debts
        for debt in debts:
            if debt['balance'] > 0:
                min_payment = min(debt['min_payment'], debt['balance'])
                debt['balance'] -= min_payment
                
                # Track minimum payment (we'll update with extra later if applicable)
                debt['payment_this_month'] = min_payment
            else:
                debt['payment_this_month'] = 0
        
        # Step 3: Apply extra payment to the FIRST active debt (already sorted by strategy)
        for i, debt in enumerate(debts):
            if debt['balance'] > 0:
                # This is the target debt - apply all available extra
                extra_to_apply = min(available_extra, debt['balance'])
                debt['balance'] -= extra_to_apply
                debt['payment_this_month'] += extra_to_apply
                
                # Check if this debt is now paid off
                if debt['balance'] <= 0.01:  # Account for floating point
                    debt['balance'] = 0
                    
                    # Record payoff
                    if not any(p['name'] == debt['name'] for p in payoff_order):
                        payoff_order.append({
                            'name': debt['name'],
                            'order': len(payoff_order) + 1,
                            'months': months
                        })
                    
                    # Roll this debt's minimum payment into extra for next month
                    available_extra += debt['min_payment']
                
                break  # Only apply extra to first active debt
        
        # Track all debts for this month
        for debt in debts:
            month_data['debts'].append({
                'name': debt['name'],
                'payment': debt['payment_this_month'],
                'interest': debt['interest_this_month'],
                'balance': max(0, debt['balance']),
                'paid_off': debt['balance'] == 0
            })
        
        monthly_breakdown.append(month_data)
    
    # Add order numbers to debts
    result_debts = []
    for debt in debts:
        payoff_info = next((p for p in payoff_order if p['name'] == debt['name']), None)
        result_debts.append({
            'name': debt['name'],
            'balance': debt['balance'],
            'interest_rate': debt['interest_rate'],
            'min_payment': debt['min_payment'],
            'order': payoff_info['order'] if payoff_info else None,
            'payoff_month': payoff_info['months'] if payoff_info else None
        })
    
    return {
        'debts': result_debts,
        'months_to_payoff': months,
        'years_to_payoff': round(months / 12, 1),
        'total_interest': total_interest,
        'total_paid': sum(d['balance'] for d in debts) + total_interest,
        'breakdown': monthly_breakdown  # NEW: Include monthly breakdown
    }
# ============================================================================
# PAYMENT TRACKING ROUTES
# ============================================================================

@login_required


@app.route('/log-payment', methods=['GET', 'POST'])
def log_payment():
    """Log a debt payment"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        debt_id = request.form.get('debt_id')
        payment_date = request.form.get('payment_date')
        amount_paid = float(request.form.get('amount_paid'))
        payment_type = request.form.get('payment_type', 'regular')
        notes = request.form.get('notes', '')
        
        # Insert payment
        conn.execute('''
            INSERT INTO payment_history (debt_id, payment_date, amount_paid, payment_type, notes)
            VALUES (%s, %s, %s, %s, %s)
        ''', (debt_id, payment_date, amount_paid, payment_type, notes))
        
        # Update debt balance
        conn.execute('''
            UPDATE debts 
            SET current_balance = current_balance - %s
            WHERE id = %s
        ''', (amount_paid, debt_id))
        
        conn.commit()
        conn.close()
        
        return redirect(url_for('payment_history'))
    
    # GET request - show form
    debts = conn.execute('''
        SELECT * FROM debts 
        WHERE is_active = 1 
        ORDER BY name
    ''').fetchall()
    
    conn.close()
    
    from datetime import date
    today = date.today().strftime('%Y-%m-%d')
    
    return render_template('log_payment.html', debts=debts, today=today)

@login_required


@app.route('/payment-history')
def payment_history():
    """View payment history"""
    conn = get_db_connection()
    
    payments = conn.execute('''
        SELECT 
            ph.id, ph.payment_date, ph.amount_paid, ph.payment_type, ph.notes,
            d.name as debt_name
        FROM payment_history ph
        JOIN debts d ON ph.debt_id = d.id
        ORDER BY ph.payment_date DESC
    ''').fetchall()
    
    debt_summaries = conn.execute('''
        SELECT 
            d.id, d.name, d.starting_balance as original_balance, d.current_balance,
            COALESCE(SUM(ph.amount_paid), 0) as total_paid,
            COUNT(ph.id) as payment_count,
            MAX(ph.payment_date) as last_payment
        FROM debts d
        LEFT JOIN payment_history ph ON d.id = ph.debt_id
        WHERE d.is_active = 1
        GROUP BY d.id
    ''').fetchall()
    
    conn.close()
    return render_template('payment_history.html', payments=payments, debt_summaries=debt_summaries)

@login_required


@app.route('/delete-payment/<int:payment_id>', methods=['POST'])
def delete_payment_history(payment_id):
    """Delete a payment"""
    conn = get_db_connection()
    payment = conn.execute('SELECT debt_id, amount_paid FROM payment_history WHERE id = %s', (payment_id,)).fetchone()
    
    if payment:
        conn.execute('UPDATE debts SET current_balance = current_balance + %s WHERE id = %s', 
                    (payment['amount_paid'], payment['debt_id']))
        conn.execute('DELETE FROM payment_history WHERE id = %s', (payment_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('payment_history'))

# ============================================================================
# BUDGET SYSTEM ROUTES
# ============================================================================

@login_required


@app.route('/budget')
def budget():
    """View budget vs actual spending"""
    conn = get_db_connection()
    
    # Get the view type (month, quarter, year)
    view_type = request.args.get('view', 'month')
    
    # Get selected month/quarter/year
    from datetime import datetime
    today = datetime.today()
    selected_month = request.args.get('month', today.to_char())
    selected_year = request.args.get('year', str(today.year))
    
    # Calculate date ranges based on view type
    if view_type == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        # Get last day of month
        import calendar
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        multiplier = 1
    elif view_type == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        import calendar
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        multiplier = 3
    else:  # year
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        multiplier = 12
    
    # Get all budgets with category/subcategory info
    budgets = conn.execute('''
        SELECT 
            b.id,
            b.category_id,
            b.subcategory_id,
            b.monthly_amount,
            c.name as category_name,
            c.color as category_color,
            sc.name as subcategory_name
        FROM budgets b
        LEFT JOIN categories c ON b.category_id = c.id
        LEFT JOIN subcategories sc ON b.subcategory_id = sc.id
        WHERE b.is_active = 1
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    # Get actual spending for the period
    spending = conn.execute('''
        SELECT 
            e.category_id,
            e.subcategory_id,
            SUM(e.amount) as total_spent
        FROM expenses e
        WHERE e.date BETWEEN %s AND %s
        GROUP BY e.category_id, e.subcategory_id
    ''', (start_date, end_date)).fetchall()
    
    conn.close()
    
    # Build spending lookup dictionary
    spending_dict = {}
    for s in spending:
        key = (s['category_id'], s['subcategory_id'] if s['subcategory_id'] else None)
        spending_dict[key] = s['total_spent']
    
    # Build budget data structure with spending
    budget_data = {}
    for b in budgets:
        cat_id = b['category_id']
        subcat_id = b['subcategory_id']
        
        if cat_id not in budget_data:
            budget_data[cat_id] = {
                'name': b['category_name'],
                'color': b['category_color'],
                'budget': 0,
                'spent': 0,
                'subcategories': {}
            }
        
        budget_amount = b['monthly_amount'] * multiplier
        spent_amount = spending_dict.get((cat_id, subcat_id), 0)
        
        if subcat_id:
            budget_data[cat_id]['subcategories'][subcat_id] = {
                'name': b['subcategory_name'],
                'budget': budget_amount,
                'spent': spent_amount
            }
            budget_data[cat_id]['budget'] += budget_amount
            budget_data[cat_id]['spent'] += spent_amount
        else:
            budget_data[cat_id]['budget'] = budget_amount
            budget_data[cat_id]['spent'] = spent_amount
    
    return render_template('budget.html',
                         budget_data=budget_data,
                         view_type=view_type,
                         selected_month=selected_month,
                         selected_year=selected_year,
                         multiplier=multiplier,
                         start_date=start_date,
                         end_date=end_date)

@login_required


@app.route('/manage-budget')
def manage_budget():
    """Manage budget amounts"""
    conn = get_db_connection()
    
    # Get all categories with subcategories
    categories = conn.execute('''
        SELECT * FROM categories ORDER BY name
    ''').fetchall()
    
    subcategories = conn.execute('''
        SELECT sc.*, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    # Get existing budgets
    budgets = conn.execute('''
        SELECT 
            b.*,
            c.name as category_name,
            sc.name as subcategory_name
        FROM budgets b
        LEFT JOIN categories c ON b.category_id = c.id
        LEFT JOIN subcategories sc ON b.subcategory_id = sc.id
        WHERE b.is_active = 1
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    # Get income categories
    income_categories = conn.execute('''
        SELECT DISTINCT category 
        FROM income 
        WHERE category IS NOT NULL AND category != ''
        ORDER BY category
    ''').fetchall()
    
    # Get existing income budgets
    income_budgets = conn.execute('''
        SELECT * FROM income_budgets 
        WHERE is_active = 1
        ORDER BY category
    ''').fetchall()
    
    conn.close()
    
    # Build budget lookup
    budget_lookup = {}
    for b in budgets:
        key = (b['category_id'], b['subcategory_id'] if b['subcategory_id'] else None)
        budget_lookup[key] = b['monthly_amount']
    
    # Build income budget lookup
    income_budget_lookup = {}
    for ib in income_budgets:
        income_budget_lookup[ib['category']] = ib['monthly_amount']
    
    return render_template('manage_budget.html',
                         categories=categories,
                         subcategories=subcategories,
                         budget_lookup=budget_lookup,
                         income_categories=income_categories,
                         income_budget_lookup=income_budget_lookup)

@login_required


@app.route('/save-budget', methods=['POST'])
def save_budget():
    """Save or update budget amounts"""
    conn = get_db_connection()
    
    # Get all form data
    for key, value in request.form.items():
        if key.startswith('budget_') and value:
            # Parse the key: budget_cat_X or budget_subcat_X
            parts = key.split('_')
            amount = float(value)
            
            if parts[1] == 'cat':
                category_id = int(parts[2])
                subcategory_id = None
            else:  # subcat
                subcategory_id = int(parts[2])
                # Get category_id for this subcategory
                subcat = conn.execute('SELECT category_id FROM subcategories WHERE id = %s', 
                                    (subcategory_id,)).fetchone()
                category_id = subcat['category_id']
            
            # Check if budget exists
            existing = conn.execute('''
                SELECT id FROM budgets 
                WHERE category_id = %s AND subcategory_id IS %s
            ''', (category_id, subcategory_id)).fetchone()
            
            if existing:
                # Update
                conn.execute('''
                    UPDATE budgets 
                    SET monthly_amount = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (amount, existing['id']))
            else:
                # Insert
                conn.execute('''
                    INSERT INTO budgets (category_id, subcategory_id, monthly_amount)
                    VALUES (%s, %s, %s)
                ''', (category_id, subcategory_id, amount))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('manage_budget'))


@login_required


@app.route('/save-income-budget', methods=['POST'])
def save_income_budget():
    """Save or update income budget amounts"""
    conn = get_db_connection()
    
    # Get all form data
    for key, value in request.form.items():
        if key.startswith('income_budget_') and value:
            category = key.replace('income_budget_', '')
            amount = float(value)
            
            # Check if income budget exists
            existing = conn.execute(
                'SELECT id FROM income_budgets WHERE category = %s',
                (category,)
            ).fetchone()
            
            if existing:
                # Update existing
                conn.execute(
                    '''UPDATE income_budgets 
                       SET monthly_amount = %s, updated_at = CURRENT_TIMESTAMP 
                       WHERE id = %s''',
                    (amount, existing['id'])
                )
            else:
                # Create new
                conn.execute(
                    '''INSERT INTO income_budgets (category, monthly_amount) 
                       VALUES (%s, %s)''',
                    (category, amount)
                )
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('manage_budget', success='Income budgets saved successfully'))


@login_required


@app.route('/delete-budget/<int:budget_id>', methods=['POST'])
def delete_budget_item(budget_id):
    """Delete a budget"""
    conn = get_db_connection()
    conn.execute('UPDATE budgets SET is_active = 0 WHERE id = %s', (budget_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_budget'))



@login_required


@app.route('/debt-tracker/delete/<int:debt_id>', methods=['POST'])
def delete_debt_item(debt_id):
    """Delete a debt (soft delete)"""
    conn = get_db_connection()
    conn.execute('UPDATE debts SET is_active = 0 WHERE id = %s', (debt_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('debt_tracker'))


# ============================================================================
# CSV IMPORT ROUTES
# ============================================================================

import csv
from io import StringIO

@login_required


@app.route('/csv-import', methods=['GET', 'POST'])
def csv_import():
    """CSV Import - Upload and column mapping"""
    conn = get_db_connection()
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    subcategories = conn.execute('''
        SELECT sc.*, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    ''').fetchall()
    conn.close()
    
    if request.method == 'POST':
        # Handle file upload
        if 'csv_file' not in request.files:
            return render_template('csv_import.html', error='No file uploaded',
                                 sources=sources, categories=categories, subcategories=subcategories)
        
        file = request.files['csv_file']
        if file.filename == '':
            return render_template('csv_import.html', error='No file selected',
                                 sources=sources, categories=categories, subcategories=subcategories)
        
        if not file.filename.endswith('.csv'):
            return render_template('csv_import.html', error='Please upload a CSV file',
                                 sources=sources, categories=categories, subcategories=subcategories)
        
        try:
            # Read CSV content
            csv_content = file.read().decode('utf-8')
            csv_reader = csv.reader(StringIO(csv_content))
            rows = list(csv_reader)
            
            if len(rows) < 2:
                return render_template('csv_import.html', error='CSV file is empty or has no data rows',
                                     sources=sources, categories=categories, subcategories=subcategories)
            
            # Check if file has headers
            no_header = request.form.get('no_header') == '1'
            
            if no_header:
                # No header row - use generic column names
                num_cols = len(rows[0]) if rows else 0
                headers = [f'Column {i+1}' for i in range(num_cols)]
                sample_rows = rows[0:5]  # First 5 rows are all data
            else:
                # First row is header
                headers = rows[0]
                sample_rows = rows[1:6]  # First 5 data rows
            
            # Try to auto-detect columns
            date_col = None
            desc_col = None
            amount_col = None
            debit_col = None
            credit_col = None
            
            for i, header in enumerate(headers):
                h = header.lower().strip()
                if any(x in h for x in ['date', 'posted', 'transaction date']):
                    date_col = i
                elif any(x in h for x in ['description', 'desc', 'memo', 'transaction', 'details', 'name']):
                    desc_col = i
                elif any(x in h for x in ['amount', 'value']):
                    amount_col = i
                elif any(x in h for x in ['debit', 'withdrawal', 'out']):
                    debit_col = i
                elif any(x in h for x in ['credit', 'deposit', 'in']):
                    credit_col = i
            
            # Store CSV in session for next step
            from flask import session
            session['csv_data'] = rows
            session['csv_filename'] = file.filename
            session['csv_no_header'] = no_header
            
            return render_template('csv_import.html',
                                 sources=sources,
                                 categories=categories,
                                 subcategories=subcategories,
                                 headers=headers,
                                 sample_rows=sample_rows,
                                 date_col=date_col,
                                 desc_col=desc_col,
                                 amount_col=amount_col,
                                 debit_col=debit_col,
                                 credit_col=credit_col,
                                 show_mapping=True)
        except Exception as e:
            return render_template('csv_import.html', error=f'Error reading CSV: {str(e)}',
                                 sources=sources, categories=categories, subcategories=subcategories)
    
    return render_template('csv_import.html',
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories)

@login_required


@app.route('/csv-preview', methods=['POST'])
def csv_preview():
    """Preview CSV data and check for duplicates"""
    from flask import session
    from datetime import datetime
    
    csv_data = session.get('csv_data', [])
    if not csv_data:
        return redirect(url_for('csv_import'))
    
    # Get column mappings from form
    date_col = int(request.form.get('date_col', 0))
    desc_col = int(request.form.get('desc_col', 1))
    amount_col = request.form.get('amount_col')
    debit_col = request.form.get('debit_col')
    credit_col = request.form.get('credit_col')
    
    # Get default source/category
    default_source = request.form.get('default_source')
    default_category = request.form.get('default_category')
    default_subcategory = request.form.get('default_subcategory')
    date_format = request.form.get('date_format', '%Y-%m-%d')
    
    conn = get_db_connection()
    
    # Get existing expenses for duplicate checking
    existing = conn.execute('SELECT date, amount FROM expenses').fetchall()
    existing_set = set((row['date'], float(row['amount'])) for row in existing)
    
    # Get sources/categories for display
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    subcategories = conn.execute('''
        SELECT sc.*, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    conn.close()
    
    # Process rows
    preview_rows = []
    no_header = session.get('csv_no_header', False)
    
    if no_header:
        headers = [f'Column {i+1}' for i in range(len(csv_data[0]))] if csv_data else []
        data_rows = csv_data
    else:
        headers = csv_data[0]
        data_rows = csv_data[1:]
    
    for row in data_rows:
        if len(row) < max(date_col, desc_col) + 1:
            continue
        
        try:
            # Parse date
            date_str = row[date_col].strip()
            try:
                parsed_date = datetime.strptime(date_str, date_format)
                formatted_date = parsed_date.strftime('%Y-%m-%d')
            except:
                # Try common formats
                for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y/%m/%d', '%m-%d-%Y']:
                    try:
                        parsed_date = datetime.strptime(date_str, fmt)
                        formatted_date = parsed_date.strftime('%Y-%m-%d')
                        break
                    except:
                        continue
                else:
                    formatted_date = date_str
            
            # Parse amount
            amount = 0
            if amount_col and amount_col != '':
                amt_str = row[int(amount_col)].replace('$', '').replace(',', '').strip()
                if amt_str:
                    amount = abs(float(amt_str))
            elif debit_col and debit_col != '':
                debit_str = row[int(debit_col)].replace('$', '').replace(',', '').strip() if int(debit_col) < len(row) else ''
                credit_str = row[int(credit_col)].replace('$', '').replace(',', '').strip() if credit_col and credit_col != '' and int(credit_col) < len(row) else ''
                
                if debit_str:
                    amount = abs(float(debit_str))
                elif credit_str:
                    amount = -abs(float(credit_str))  # Credits are negative (income)
            
            if amount == 0:
                continue
            
            # Get description
            description = row[desc_col].strip() if desc_col < len(row) else ''
            
            # Check for duplicate
            is_duplicate = (formatted_date, abs(amount)) in existing_set
            
            preview_rows.append({
                'date': formatted_date,
                'description': description,
                'amount': amount,
                'is_duplicate': is_duplicate,
                'selected': not is_duplicate  # Pre-select non-duplicates
            })
        except Exception as e:
            print(f"Error processing row: {e}")
            continue
    
    # Store preview data in session
    session['preview_rows'] = preview_rows
    session['default_source'] = default_source
    session['default_category'] = default_category
    session['default_subcategory'] = default_subcategory
    
    duplicate_count = sum(1 for r in preview_rows if r['is_duplicate'])
    new_count = len(preview_rows) - duplicate_count
    
    return render_template('csv_preview.html',
                         preview_rows=preview_rows,
                         duplicate_count=duplicate_count,
                         new_count=new_count,
                         sources=sources,
                         categories=categories,
                         subcategories=subcategories,
                         default_source=default_source,
                         default_category=default_category,
                         default_subcategory=default_subcategory)

@login_required


@app.route('/csv-do-import', methods=['POST'])
def csv_do_import():
    """Actually import selected CSV rows"""
    from flask import session
    
    preview_rows = session.get('preview_rows', [])
    default_source = session.get('default_source')
    default_category = session.get('default_category')
    default_subcategory = session.get('default_subcategory')
    
    if not preview_rows:
        return redirect(url_for('csv_import'))
    
    # Get selected rows from form
    selected_indices = request.form.getlist('selected_rows')
    selected_indices = [int(i) for i in selected_indices]
    
    conn = get_db_connection()
    imported_count = 0
    
    for i in selected_indices:
        if i < len(preview_rows):
            row = preview_rows[i]
            
            # Get individual overrides if provided
            source_id = request.form.get(f'source_{i}', default_source)
            category_id = request.form.get(f'category_{i}', default_category)
            subcategory_id = request.form.get(f'subcategory_{i}', default_subcategory)
            
            # Insert expense
            conn.execute('''
                INSERT INTO expenses (date, description, amount, source_id, category_id, subcategory_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (row['date'], row['description'], abs(row['amount']), 
                source_id or None, category_id or None, subcategory_id or None))
            imported_count += 1
    
    conn.commit()
    conn.close()
    
    # Clear session data
    session.pop('csv_data', None)
    session.pop('preview_rows', None)
    session.pop('default_source', None)
    session.pop('default_category', None)
    session.pop('default_subcategory', None)
    
    return redirect(url_for('view_expenses', success=f'Successfully imported {imported_count} expenses'))


# ============================================================================
# INCOME TRACKING ROUTES
# ============================================================================

@login_required


@app.route('/income')
def income():
    """View all income"""
    conn = get_db_connection()
    
    # Get filter parameters
    filter_period = request.args.get('period', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Build query
    where_clauses = []
    params = []
    
    from datetime import datetime, timedelta
    today = datetime.now().date()
    
    if filter_period == 'mtd':
        start_of_month = today.replace(day=1)
        where_clauses.append('date >= %s')
        params.append(start_of_month.isoformat())
    elif filter_period == 'ytd':
        start_of_year = today.replace(month=1, day=1)
        where_clauses.append('date >= %s')
        params.append(start_of_year.isoformat())
    elif filter_period == 'custom' and start_date:
        where_clauses.append('date >= %s')
        params.append(start_date)
        if end_date:
            where_clauses.append('date <= %s')
            params.append(end_date)
    
    where_sql = ' AND '.join(where_clauses) if where_clauses else '1=1'
    
    income_records = conn.execute(f'''
        SELECT * FROM income
        WHERE {where_sql}
        ORDER BY date DESC
    ''', params).fetchall()
    
    # Get totals
    total_income = conn.execute(f'''
        SELECT COALESCE(SUM(amount), 0) as total FROM income
        WHERE {where_sql}
    ''', params).fetchone()['total']
    
    # Get income by category
    by_category = conn.execute(f'''
        SELECT category, SUM(amount) as total
        FROM income
        WHERE {where_sql}
        GROUP BY category
        ORDER BY total DESC
    ''', params).fetchall()
    
    categories = conn.execute('SELECT * FROM income_categories ORDER BY name').fetchall()
    
    conn.close()
    
    return render_template('income.html',
                         income_records=income_records,
                         total_income=total_income,
                         by_category=by_category,
                         categories=categories,
                         filter_period=filter_period,
                         start_date=start_date,
                         end_date=end_date)

@login_required


@app.route('/add-income', methods=['GET', 'POST'])
def add_income():
    """Add new income"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        date = request.form['date']
        source = request.form['source']
        description = request.form.get('description', '')
        category = request.form['category']
        amount = float(request.form['amount'])
        notes = request.form.get('notes', '')
        is_recurring = request.form.get('is_recurring') == 'on'
        recurring_frequency = request.form.get('recurring_frequency', '')
        recurring_day_of_week = request.form.get('recurring_day_of_week', type=int)
        recurring_day_of_month = request.form.get('recurring_day_of_month', type=int)
        recurring_end_date = request.form.get('recurring_end_date') or None
        
        recurring_id = None
        
        if is_recurring and recurring_frequency:
            cursor = conn.execute('''
                INSERT INTO recurring_income (source, description, category,
                    amount, notes, frequency, day_of_week, day_of_month,
                    start_date, end_date, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            ''', (source, description, category, amount, notes,
                  recurring_frequency, recurring_day_of_week,
                  recurring_day_of_month, date, recurring_end_date))
            recurring_id = cursor.lastrowid
            print(f"Created recurring income ID: {recurring_id}, frequency: {recurring_frequency}")
            generate_recurring_income(conn, recurring_id)
        
        conn.execute('''
            INSERT INTO income (date, source, description, category, amount, notes, recurring_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (date, source, description, category, amount, notes, recurring_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('income'))
    
    categories = conn.execute('SELECT * FROM income_categories ORDER BY name').fetchall()
    
    # Get active recurring income for duplicate check
    recurring = conn.execute('''
        SELECT * FROM recurring_income WHERE is_active = 1 ORDER BY description
    ''').fetchall()
    
    conn.close()
    
    from datetime import date
    today = date.today().strftime('%Y-%m-%d')
    
    return render_template('add_income.html', categories=categories, today=today, recurring=recurring)

@login_required


@app.route('/edit-income/<int:income_id>', methods=['GET', 'POST'])
def edit_income(income_id):
    """Edit income record"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        date = request.form['date']
        source = request.form['source']
        description = request.form.get('description', '')
        category = request.form['category']
        amount = float(request.form['amount'])
        notes = request.form.get('notes', '')
        
        conn.execute('''
            UPDATE income
            SET date = %s, source = %s, description = %s, category = %s, amount = %s, notes = %s
            WHERE id = %s
        ''', (date, source, description, category, amount, notes, income_id))
        conn.commit()
        conn.close()
        
        return redirect(url_for('income'))
    
    income_record = conn.execute('SELECT * FROM income WHERE id = %s', (income_id,)).fetchone()
    categories = conn.execute('SELECT * FROM income_categories ORDER BY name').fetchall()
    conn.close()
    
    return render_template('edit_income.html', income=income_record, categories=categories)

@login_required


@app.route('/delete-income/<int:income_id>', methods=['POST'])
def delete_income(income_id):
    """Delete income record"""
    conn = get_db_connection()
    conn.execute('DELETE FROM income WHERE id = %s', (income_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('income'))


@login_required


@app.route('/manage/income-categories')
def manage_income_categories():
    """Manage income categories"""
    conn = get_db_connection()
    income_categories = conn.execute('SELECT * FROM income_categories ORDER BY name').fetchall()
    conn.close()
    return render_template('manage_income_categories.html', income_categories=income_categories)

@login_required


@app.route('/manage/income-categories/add', methods=['POST'])
def add_income_category():
    """Add new income category"""
    name = request.form['name'].strip()
    description = request.form.get('description', '').strip()
    
    if name:
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO income_categories (name, description) VALUES (%s, %s)', 
                        (name, description))
            conn.commit()
        except:
            pass  # Already exists
        conn.close()
    
    return redirect(url_for('manage_income_categories'))

@login_required


@app.route('/manage/income-categories/delete/<int:cat_id>', methods=['POST'])
def delete_income_category(cat_id):
    """Delete income category"""
    conn = get_db_connection()
    conn.execute('DELETE FROM income_categories WHERE id = %s', (cat_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_income_categories'))


@login_required


@app.route('/convert-to-income/<int:expense_id>')
def convert_to_income(expense_id):
    """Convert an expense to income"""
    conn = get_db_connection()
    
    # Get the expense
    expense = conn.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    
    if expense:
        # Insert into income table
        conn.execute('''
            INSERT INTO income (date, source, description, category, amount, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            expense['date'],
            expense['description'][:50] if expense['description'] else 'Unknown',
            expense['description'],
            'Other',  # Default category, user can edit later
            expense['amount'],
            'Converted from expense'
        ))
        
        # Delete from expenses
        conn.execute('DELETE FROM expenses WHERE id = %s', (expense_id,))
        conn.commit()
    
    conn.close()
    
    return redirect(url_for('income'))


@login_required



@app.route('/convert-to-expense/<int:income_id>')
@login_required
def convert_to_expense(income_id):
    conn = get_db_connection()
    income_entry = conn.execute('SELECT * FROM income WHERE id = %s', (income_id,)).fetchone()
    
    if income_entry:
        default_cat = conn.execute('SELECT id FROM categories LIMIT 1').fetchone()
        default_src = conn.execute('SELECT id FROM sources LIMIT 1').fetchone()
        
        conn.execute('''INSERT INTO expenses (date, description, amount, category_id, source_id, notes, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)''',
                     (income_entry['date'],
                      f"{income_entry['source']} - {income_entry['category']}",
                      income_entry['amount'],
                      None,  # Blank category
                      default_src['id'],
                      f"Converted from income: {income_entry['category']}"))
        
        conn.execute('DELETE FROM income WHERE id = %s', (income_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('view_expenses'))



@app.route('/budget/export-pdf')
def budget_export_pdf():
    """Export budget report as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from io import BytesIO
    from datetime import datetime
    import calendar
    
    # Get the same parameters as the budget view
    view_type = request.args.get('view', 'month')
    selected_month = request.args.get('month', datetime.today().to_char())
    selected_year = request.args.get('year', str(datetime.today().year))
    
    # Calculate date ranges (same as budget route)
    today = datetime.today()
    if view_type == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        multiplier = 1
        period_label = f"{calendar.month_name[int(month)]} {year}"
    elif view_type == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        multiplier = 3
        period_label = f"Q{quarter} {year}"
    else:  # year
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        multiplier = 12
        period_label = f"Year {year}"
    
    # Get budget data (same queries as budget route)
    conn = get_db_connection()
    
    budgets = conn.execute('''
        SELECT b.id, b.category_id, b.subcategory_id, b.monthly_amount,
               c.name as category_name, c.color as category_color,
               sc.name as subcategory_name
        FROM budgets b
        LEFT JOIN categories c ON b.category_id = c.id
        LEFT JOIN subcategories sc ON b.subcategory_id = sc.id
        WHERE b.is_active = 1
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    spending = conn.execute('''
        SELECT e.category_id, e.subcategory_id, SUM(e.amount) as total_spent
        FROM expenses e
        WHERE e.date BETWEEN %s AND %s
        GROUP BY e.category_id, e.subcategory_id
    ''', (start_date, end_date)).fetchall()
    
    conn.close()
    
    # Build spending lookup
    spending_dict = {}
    for s in spending:
        key = (s['category_id'], s['subcategory_id'] if s['subcategory_id'] else None)
        spending_dict[key] = s['total_spent']
    
    # Build budget data structure
    budget_data = {}
    for b in budgets:
        cat_id = b['category_id']
        subcat_id = b['subcategory_id']
        
        if cat_id not in budget_data:
            budget_data[cat_id] = {
                'name': b['category_name'],
                'color': b['category_color'],
                'budget': 0,
                'spent': 0,
                'subcategories': {}
            }
        
        budget_amount = b['monthly_amount'] * multiplier
        spent_amount = spending_dict.get((cat_id, subcat_id), 0)
        
        if subcat_id:
            budget_data[cat_id]['subcategories'][subcat_id] = {
                'name': b['subcategory_name'],
                'budget': budget_amount,
                'spent': spent_amount
            }
            budget_data[cat_id]['budget'] += budget_amount
            budget_data[cat_id]['spent'] += spent_amount
        else:
            budget_data[cat_id]['budget'] = budget_amount
            budget_data[cat_id]['spent'] = spent_amount
    
    # Calculate totals
    total_budget = sum(cat['budget'] for cat in budget_data.values())
    total_spent = sum(cat['spent'] for cat in budget_data.values())
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.75*inch, bottomMargin=0.5*inch)
    
    # Container for PDF elements
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    # Title
    elements.append(Paragraph(f"Budget Report - {period_label}", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=10, textColor=colors.grey, alignment=TA_CENTER)))
    elements.append(Spacer(1, 0.3*inch))
    
    # Summary table
    summary_data = [
        ['Total Budget', 'Total Spent', 'Remaining', '% Used'],
        [f'${total_budget:,.2f}', f'${total_spent:,.2f}', 
         f'${total_budget - total_spent:,.2f}', 
         f'{(total_spent/total_budget*100) if total_budget > 0 else 0:.1f}%']
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch, 2*inch, 1.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.4*inch))
    
    # Category breakdown
    for cat_id, cat_data in budget_data.items():
        cat_percent = (cat_data['spent'] / cat_data['budget'] * 100) if cat_data['budget'] > 0 else 0
        
        # Category header
        cat_header_style = ParagraphStyle(
            'CategoryHeader',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#495057'),
            spaceAfter=10
        )
        elements.append(Paragraph(f"{cat_data['name']}", cat_header_style))
        
        # Category summary row
        cat_summary = [[
            'Budget', 'Spent', 'Remaining', '% Used'
        ], [
            f"${cat_data['budget']:,.2f}",
            f"${cat_data['spent']:,.2f}",
            f"${cat_data['budget'] - cat_data['spent']:,.2f}",
            f"{cat_percent:.1f}%"
        ]]
        
        cat_table = Table(cat_summary, colWidths=[1.8*inch, 1.8*inch, 1.8*inch, 1.3*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(cat_table)
        
        # Subcategories if any
        if cat_data['subcategories']:
            subcat_data = [['Subcategory', 'Budget', 'Spent', '% Used']]
            for subcat_id, subcat in cat_data['subcategories'].items():
                sub_percent = (subcat['spent'] / subcat['budget'] * 100) if subcat['budget'] > 0 else 0
                subcat_data.append([
                    subcat['name'],
                    f"${subcat['budget']:,.2f}",
                    f"${subcat['spent']:,.2f}",
                    f"{sub_percent:.0f}%"
                ])
            
            subcat_table = Table(subcat_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch, 1.2*inch])
            subcat_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e9ecef')),
                ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 1), (0, -1), 20),
            ]))
            elements.append(Spacer(1, 0.1*inch))
            elements.append(subcat_table)
        
        elements.append(Spacer(1, 0.3*inch))
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=budget_report_{period_label.replace(" ", "_")}.pdf'
    
    return response


# ============================================================================
# PROFIT & LOSS STATEMENT ROUTES
# ============================================================================

@login_required


@app.route('/profit-loss')
def profit_loss():
    """Profit & Loss Statement"""
    from datetime import datetime, timedelta
    import calendar
    
    # Get parameters
    view_type = request.args.get('view', 'month')
    selected_month = request.args.get('month', datetime.today().to_char())
    selected_year = request.args.get('year', str(datetime.today().year))
    
    # Check if forecast mode (include future) or actual mode (past only)
    include_forecast = request.args.get('forecast', 'false') == 'true'
    
    # Calculate date ranges
    today = datetime.today()
    today_str = today.strftime('%Y-%m-%d')
    if view_type == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        multiplier = 1
        period_label = f"{calendar.month_name[int(month)]} {year}"
        
        # Last year same month
        ly_year = int(year) - 1
        ly_start_date = f"{ly_year}-{month}-01"
        ly_last_day = calendar.monthrange(ly_year, int(month))[1]
        ly_end_date = f"{ly_year}-{month}-{ly_last_day:02d}"
        
    elif view_type == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        multiplier = 3
        period_label = f"Q{quarter} {year}"
        
        # Last year same quarter
        ly_year = year - 1
        ly_start_date = f"{ly_year}-{start_month:02d}-01"
        ly_last_day = calendar.monthrange(ly_year, end_month)[1]
        ly_end_date = f"{ly_year}-{end_month:02d}-{ly_last_day:02d}"
        
    else:  # year
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        multiplier = 12
        period_label = f"Year {year}"
        
        # Last year
        ly_year = year - 1
        ly_start_date = f"{ly_year}-01-01"
        ly_end_date = f"{ly_year}-12-31"
    
    conn = get_db_connection()
    
    # Get Income data (Current Year)
    # If not in forecast mode, cap end_date at today
    actual_end_date = end_date if include_forecast else min(end_date, today_str)
    
    income_by_category = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM income
        WHERE date BETWEEN ? AND ?
        GROUP BY category
        ORDER BY category
    ''', (start_date, actual_end_date)).fetchall()
    
    total_income = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total
        FROM income
        WHERE date BETWEEN ? AND ?
    ''', (start_date, actual_end_date)).fetchone()['total']
    
    # Get Income data (Last Year)
    ly_income_by_category = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM income
        WHERE date BETWEEN ? AND ?
        GROUP BY category
        ORDER BY category
    ''', (ly_start_date, ly_end_date)).fetchall()
    
    ly_total_income = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total
        FROM income
        WHERE date BETWEEN ? AND ?
    ''', (ly_start_date, ly_end_date)).fetchone()['total']
    
    # Get Expense data by category (Current Year)
    # Use actual_end_date (already calculated for income)
    # Exclude parent splits (is_split = 1) to avoid double-counting
    expense_by_category = conn.execute('''
        SELECT c.id, c.name, c.color, SUM(e.amount) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN ? AND ?
          AND (e.is_split IS NULL OR e.is_split != 1)
        GROUP BY c.id, c.name, c.color
        ORDER BY c.name
    ''', (start_date, actual_end_date)).fetchall()
    
    print(f"\nDEBUG P&L: Date range {start_date} to {actual_end_date}")
    print(f"DEBUG P&L: Found {len(expense_by_category)} expense categories:")
    for exp in expense_by_category:
        print(f"  - {exp['name']}: ${exp['total']:.2f}")
    
    total_expenses = conn.execute('''
        SELECT COALESCE(SUM(e.amount), 0) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN ? AND ?
          AND (e.is_split IS NULL OR e.is_split != 1)
    ''', (start_date, actual_end_date)).fetchone()['total']



    
    # Get Expense data by category (Last Year)
    ly_expense_by_category = conn.execute('''
        SELECT c.id, c.name, c.color, SUM(e.amount) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN ? AND ?
          AND (e.is_split IS NULL OR e.is_split != 1)
        GROUP BY c.id, c.name, c.color
        ORDER BY c.name
    ''', (ly_start_date, ly_end_date)).fetchall()
    
    ly_total_expenses = conn.execute('''
        SELECT COALESCE(SUM(e.amount), 0) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN ? AND ?
          AND (e.is_split IS NULL OR e.is_split != 1)
    ''', (ly_start_date, ly_end_date)).fetchone()['total']    
        # Get Budget data (Expenses)
    budgets = conn.execute('''
        SELECT b.category_id, b.subcategory_id, b.monthly_amount,
               c.name as category_name
        FROM budgets b
        LEFT JOIN categories c ON b.category_id = c.id
        WHERE b.is_active = 1
    ''').fetchall()
    
    # Get Income Budget data
    income_budgets = conn.execute('''
        SELECT category, monthly_amount
        FROM income_budgets
        WHERE is_active = 1
    ''').fetchall()
    
    # Calculate tax summary (BEFORE closing connection)
    tax_summary = conn.execute('''
        SELECT 
            tr.name as tax_name,
            tr.rate as tax_rate,
            SUM(e.tax_amount) as total_tax
        FROM expenses e
        JOIN tax_rates tr ON e.tax_rate_id = tr.id
        WHERE e.date BETWEEN ? AND ?
        GROUP BY tr.id, tr.name, tr.rate
        ORDER BY tr.display_order
    ''', (start_date, actual_end_date)).fetchall()
    
    total_tax_paid = sum(row['total_tax'] for row in tax_summary) if tax_summary else 0
    
    conn.close()
    
    # Calculate income budget totals (BEFORE conn.close() usage)
    income_budget_by_category = {}
    total_income_budget = 0
    for ib in income_budgets:
        income_budget_by_category[ib['category']] = ib['monthly_amount'] * multiplier
        total_income_budget += ib['monthly_amount'] * multiplier
    
    # Calculate actual multiplier based on date range shown
    # If in actual mode, adjust multiplier to match actual period
    if not include_forecast and view_type in ['quarter', 'year']:
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        actual_end_dt = datetime.strptime(actual_end_date, '%Y-%m-%d')
        
        # Calculate months between start and actual end
        months_diff = (actual_end_dt.year - start_dt.year) * 12 + (actual_end_dt.month - start_dt.month)
        
        # Include partial month if we're not at month end
        if actual_end_dt.day > 1:
            months_diff += 1
        
        # Override multiplier for budget calculation
        actual_multiplier = max(1, months_diff)
    else:
        actual_multiplier = multiplier
    
    # Build budget lookup by category
    budget_by_category = {}
    for b in budgets:
        cat_id = b['category_id']
        if cat_id not in budget_by_category:
            budget_by_category[cat_id] = 0
        budget_by_category[cat_id] += b['monthly_amount'] * actual_multiplier
    
    total_budget = sum(budget_by_category.values())
    
    # Calculate net income
    net_income = total_income - total_expenses
    budget_net = 0 - total_budget  # Budget net (no income budget yet)
    
    # Build LY lookups
    ly_income_dict = {inc['category']: inc['total'] for inc in ly_income_by_category}
    ly_expense_dict = {exp['id']: exp['total'] for exp in ly_expense_by_category}
    
    # Calculate LY net income
    ly_net_income = ly_total_income - ly_total_expenses
    
    return render_template('profit_loss.html',
                         view_type=view_type,
                         selected_month=selected_month,
                         selected_year=selected_year,
                         period_label=period_label,
                         start_date=start_date,
                         end_date=end_date,
                         income_by_category=income_by_category,
                         total_income=total_income,
                         income_budget_by_category=income_budget_by_category,
                         total_income_budget=total_income_budget,
                         expense_by_category=expense_by_category,
                         total_expenses=total_expenses,
                         budget_by_category=budget_by_category,
                         total_budget=total_budget,
                         net_income=net_income,
                         budget_net=budget_net,
                         ly_income_dict=ly_income_dict,
                         ly_expense_dict=ly_expense_dict,
                         ly_total_income=ly_total_income,
                         ly_total_expenses=ly_total_expenses,
                         ly_net_income=ly_net_income,
                         tax_summary=tax_summary,
                         total_tax_paid=total_tax_paid)


@login_required


@app.route('/pl-export-pdf')
def pl_export_pdf():
    """Export P&L as PDF with Last Year comparison"""
    
    # Get forecast mode parameter
    include_forecast = request.args.get('forecast', 'false') == 'true' 
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO
    from datetime import datetime
    import calendar
    
    # Get parameters
    view_type = request.args.get('view', 'month')
    selected_month = request.args.get('month', datetime.today().to_char())
    selected_year = request.args.get('year', str(datetime.today().year))
    
    # Calculate date ranges (Current Year)
    today = datetime.today()
    today_str = today.strftime('%Y-%m-%d')
    
    if view_type == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        multiplier = 1
        period_label = f"{calendar.month_name[int(month)]} {year}"
        
        # Last year same month
        ly_year = int(year) - 1
        ly_start_date = f"{ly_year}-{month}-01"
        ly_last_day = calendar.monthrange(ly_year, int(month))[1]
        ly_end_date = f"{ly_year}-{month}-{ly_last_day:02d}"
        
    elif view_type == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        multiplier = 3
        period_label = f"Q{quarter} {year}"
        
        # Last year same quarter
        ly_year = year - 1
        ly_start_date = f"{ly_year}-{start_month:02d}-01"
        ly_last_day = calendar.monthrange(ly_year, end_month)[1]
        ly_end_date = f"{ly_year}-{end_month:02d}-{ly_last_day:02d}"
        
    else:  # year
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        multiplier = 12
        period_label = f"Year {year}"
        
        # Last year
        ly_year = year - 1
        ly_start_date = f"{ly_year}-01-01"
        ly_end_date = f"{ly_year}-12-31"
    
    conn = get_db_connection()
    
    # Get Income data (Current Year)
    # If not in forecast mode, cap end_date at today
    actual_end_date = end_date if include_forecast else min(end_date, today_str)
    
    income_by_category = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM income
        WHERE date BETWEEN %s AND %s
        GROUP BY category
        ORDER BY category
    ''', (start_date, actual_end_date)).fetchall()
    
    total_income = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total
        FROM income
        WHERE date BETWEEN %s AND %s
    ''', (start_date, actual_end_date)).fetchone()['total']
    
    # Get Income data (Last Year)
    ly_income_by_category = conn.execute('''
        SELECT category, SUM(amount) as total
        FROM income
        WHERE date BETWEEN %s AND %s
        GROUP BY category
        ORDER BY category
    ''', (ly_start_date, ly_end_date)).fetchall()
    
    ly_total_income = conn.execute('''
        SELECT COALESCE(SUM(amount), 0) as total
        FROM income
        WHERE date BETWEEN %s AND %s
    ''', (ly_start_date, ly_end_date)).fetchone()['total']
    
    # Get Expense data (Current Year)
    expense_by_category = conn.execute('''
        SELECT c.id, c.name, SUM(e.amount) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN %s AND %s
        GROUP BY c.id, c.name
        ORDER BY c.name
    ''', (start_date, end_date)).fetchall()
    
    total_expenses = conn.execute('''
        SELECT COALESCE(SUM(e.amount), 0) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN %s AND %s
    ''', (start_date, end_date)).fetchone()['total']
    
    # Get Expense data (Last Year)
    ly_expense_by_category = conn.execute('''
        SELECT c.id, c.name, SUM(e.amount) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN %s AND %s
        GROUP BY c.id, c.name
        ORDER BY c.name
    ''', (ly_start_date, ly_end_date)).fetchall()
    
    ly_total_expenses = conn.execute('''
        SELECT COALESCE(SUM(e.amount), 0) as total
        FROM expenses e
        JOIN categories c ON e.category_id = c.id
        WHERE e.date BETWEEN %s AND %s
          AND (e.is_split IS NULL OR e.is_split != 1)
    ''', (ly_start_date, ly_end_date)).fetchone()['total']
    
    # Get Budget data
    budgets = conn.execute('''
        SELECT b.category_id, b.monthly_amount
        FROM budgets b
        WHERE b.is_active = 1
    ''').fetchall()
    
    conn.close()
    
    # Build lookups
    budget_by_category = {}
    for b in budgets:
        cat_id = b['category_id']
        if cat_id not in budget_by_category:
            budget_by_category[cat_id] = 0
        budget_by_category[cat_id] += b['monthly_amount'] * multiplier
    
    ly_income_dict = {inc['category']: inc['total'] for inc in ly_income_by_category}
    ly_expense_dict = {exp['id']: exp['total'] for exp in ly_expense_by_category}
    
    total_budget = sum(budget_by_category.values())
    net_income = total_income - total_expenses
    ly_net_income = ly_total_income - ly_total_expenses
    
    # Create PDF (LANDSCAPE for more columns)
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.4*inch, leftMargin=0.4*inch,
                           topMargin=0.6*inch, bottomMargin=0.4*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=8,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("PROFIT & LOSS STATEMENT", title_style))
    elements.append(Paragraph(f"{period_label}", 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=12, alignment=TA_CENTER, spaceAfter=3)))
    elements.append(Paragraph(f"{start_date} to {end_date}", 
                             ParagraphStyle('date', parent=styles['Normal'], 
                                          fontSize=9, textColor=colors.grey, alignment=TA_CENTER)))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y')}", 
                             ParagraphStyle('generated', parent=styles['Normal'], 
                                          fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=12)))
    
    # Build P&L table with LY columns
    data = [['Account', 'Budget', 'Actual', 'Variance', 'Last Year', 'YoY Change']]
    
    # Income section
    data.append(['INCOME', '', '', '', '', ''])
    
    for income in income_by_category:
        ly_amount = ly_income_dict.get(income['category'], 0)
        yoy_change = income['total'] - ly_amount
        
        data.append([
            f"  {income['category']}",
            '-',
            f"${income['total']:,.2f}",
            '-',
            f"${ly_amount:,.2f}" if ly_amount > 0 else '-',
            f"${yoy_change:+,.2f}" if ly_amount > 0 else '-'
        ])
    
    # Total Income
    income_yoy = total_income - ly_total_income
    data.append([
        'Total Income',
        '-',
        f"${total_income:,.2f}",
        '-',
        f"${ly_total_income:,.2f}" if ly_total_income > 0 else '-',
        f"${income_yoy:+,.2f}" if ly_total_income > 0 else '-'
    ])
    data.append(['', '', '', '', '', ''])  # Spacer
    
    # Expenses section
    data.append(['EXPENSES', '', '', '', '', ''])
    
    for expense in expense_by_category:
        budget = budget_by_category.get(expense['id'], 0)
        variance = budget - expense['total']
        ly_amount = ly_expense_dict.get(expense['id'], 0)
        yoy_change = expense['total'] - ly_amount
        
        data.append([
            f"  {expense['name']}",
            f"${budget:,.2f}" if budget > 0 else '-',
            f"${expense['total']:,.2f}",
            f"${variance:+,.2f}" if budget > 0 else '-',
            f"${ly_amount:,.2f}" if ly_amount > 0 else '-',
            f"${yoy_change:+,.2f}" if ly_amount > 0 else '-'
        ])
    
    # Total Expenses
    exp_variance = total_budget - total_expenses if total_budget > 0 else 0
    exp_yoy = total_expenses - ly_total_expenses
    data.append([
        'Total Expenses',
        f"${total_budget:,.2f}" if total_budget > 0 else '-',
        f"${total_expenses:,.2f}",
        f"${exp_variance:+,.2f}" if total_budget > 0 else '-',
        f"${ly_total_expenses:,.2f}" if ly_total_expenses > 0 else '-',
        f"${exp_yoy:+,.2f}" if ly_total_expenses > 0 else '-'
    ])
    data.append(['', '', '', '', '', ''])  # Spacer
    
    # Net Income
    net_yoy = net_income - ly_net_income
    data.append([
        'NET INCOME',
        '-',
        f"${net_income:,.2f}",
        '-',
        f"${ly_net_income:,.2f}" if ly_net_income != 0 else '-',
        f"${net_yoy:+,.2f}" if ly_net_income != 0 else '-'
    ])
    
    # Create table
    table = Table(data, colWidths=[2.2*inch, 1.3*inch, 1.3*inch, 1.2*inch, 1.3*inch, 1.2*inch])
    
    # Style table
    table_style = TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        
        # All cells
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (0, 1), (0, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ])
    
    # Find section headers and totals
    for i, row in enumerate(data):
        if row[0] in ['INCOME', 'EXPENSES']:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#e9ecef'))
            table_style.add('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold')
        elif row[0] in ['Total Income', 'Total Expenses']:
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f8f9fa'))
            table_style.add('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold')
            table_style.add('LINEABOVE', (0, i), (-1, i), 1.5, colors.black)
        elif row[0] == 'NET INCOME':
            table_style.add('BACKGROUND', (0, i), (-1, i), colors.HexColor('#667eea'))
            table_style.add('TEXTCOLOR', (0, i), (-1, i), colors.whitesmoke)
            table_style.add('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold')
            table_style.add('FONTSIZE', (0, i), (-1, i), 10)
            table_style.add('LINEABOVE', (0, i), (-1, i), 2, colors.black)
    
    table.setStyle(table_style)
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=PL_Statement_{period_label.replace(" ", "_")}.pdf'
    
    return response




@login_required


@app.route('/api/expense-details')
def api_expense_details():
    """Get expense transactions for a category and date range"""
    from datetime import datetime
    
    category_id = request.args.get('category_id', type=int)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    include_forecast = request.args.get('forecast', 'false') == 'true'
    
    if not all([category_id, start_date, end_date]):
        return jsonify([])
    
    # If not in forecast mode, cap end_date at today
    if not include_forecast:
        today = datetime.now().strftime('%Y-%m-%d')
        end_date = min(end_date, today)
    
    conn = get_db_connection()
    expenses = conn.execute('''
        SELECT e.date, e.description, e.amount, 
               v.name as vendor,
               sc.name as subcategory
        FROM expenses e
        LEFT JOIN vendors v ON e.vendor_id = v.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        WHERE e.category_id = %s 
        AND e.date BETWEEN %s AND %s
        AND (e.is_split IS NULL OR e.is_split != 1)
        ORDER BY e.date DESC
    ''', (category_id, start_date, end_date)).fetchall()
    conn.close()
    
    return jsonify([dict(exp) for exp in expenses])

@login_required


@app.route('/api/income-details')
def api_income_details():
    """Get income transactions for a category and date range"""
    category = request.args.get('category')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if not all([category, start_date, end_date]):
        return jsonify([])
    
    conn = get_db_connection()
    income = conn.execute('''
        SELECT date, source, description, amount
        FROM income
        WHERE category = %s 
        AND date BETWEEN %s AND %s
        ORDER BY date DESC
    ''', (category, start_date, end_date)).fetchall()
    conn.close()
    
    return jsonify([dict(inc) for inc in income])


# ============================================================================
# QUERY/ANALYSIS PAGE
# ============================================================================

@login_required


@app.route('/query-analysis')
def query_analysis():
    """Query and analyze expenses by various filters"""
    from datetime import datetime
    import calendar
    
    # Get filter parameters
    filter_type = request.args.get('filter_type', 'category')  # category, vendor, subcategory
    filter_value = request.args.get('filter_value', '')
    time_period = request.args.get('time_period', 'month')
    selected_month = request.args.get('month', datetime.today().to_char())
    selected_year = request.args.get('year', str(datetime.today().year))
    custom_start = request.args.get('custom_start', '')
    custom_end = request.args.get('custom_end', '')
    
    # Calculate date range
    today = datetime.today()
    if time_period == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        period_label = f"{calendar.month_name[int(month)]} {year}"
    elif time_period == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        period_label = f"Q{quarter} {year}"
    elif time_period == 'year':
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        period_label = f"Year {year}"
    elif time_period == 'custom' and custom_start and custom_end:
        start_date = custom_start
        end_date = custom_end
        period_label = f"{start_date} to {end_date}"
    else:
        # Default to current month
        year = today.year
        month = today.month
        start_date = f"{year}-{month:02d}-01"
        last_day = calendar.monthrange(year, month)[1]
        end_date = f"{year}-{month:02d}-{last_day:02d}"
        period_label = f"{calendar.month_name[month]} {year}"
    
    conn = get_db_connection()
    
    # Get filter options
    categories = conn.execute('SELECT id, name, color FROM categories ORDER BY name').fetchall()
    vendors = conn.execute('SELECT id, name FROM vendors ORDER BY name').fetchall()
    subcategories = conn.execute('''
        SELECT sc.id, sc.name, c.name as category_name
        FROM subcategories sc
        JOIN categories c ON sc.category_id = c.id
        ORDER BY c.name, sc.name
    ''').fetchall()
    
    # Build query based on filters
    transactions = []
    total_amount = 0
    transaction_count = 0
    avg_amount = 0
    category_breakdown = []
    vendor_breakdown = []
    
    if filter_value:
        base_query = '''
            SELECT e.id, e.date, e.description, e.amount,
                   c.name as category_name, c.color as category_color,
                   sc.name as subcategory_name,
                   v.name as vendor_name
            FROM expenses e
            LEFT JOIN categories c ON e.category_id = c.id
            LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
            LEFT JOIN vendors v ON e.vendor_id = v.id
            WHERE e.date BETWEEN %s AND %s
        '''
        
        params = [start_date, end_date]
        
        if filter_type == 'category':
            base_query += ' AND e.category_id = %s'
            params.append(int(filter_value))
        elif filter_type == 'vendor':
            base_query += ' AND e.vendor_id = %s'
            params.append(int(filter_value))
        elif filter_type == 'subcategory':
            base_query += ' AND e.subcategory_id = %s'
            params.append(int(filter_value))
        
        base_query += ' ORDER BY e.date DESC'
        
        transactions = conn.execute(base_query, params).fetchall()
        
        # Calculate stats
        if transactions:
            total_amount = sum(t['amount'] for t in transactions)
            transaction_count = len(transactions)
            avg_amount = total_amount / transaction_count if transaction_count > 0 else 0
            
            # Category breakdown (if filtering by vendor)
            if filter_type == 'vendor':
                category_breakdown = conn.execute('''
                    SELECT c.name, c.color, SUM(e.amount) as total, COUNT(*) as count
                    FROM expenses e
                    JOIN categories c ON e.category_id = c.id
                    WHERE e.vendor_id = %s AND e.date BETWEEN %s AND %s
                    GROUP BY c.id, c.name, c.color
                    ORDER BY total DESC
                ''', (int(filter_value), start_date, end_date)).fetchall()
            
            # Vendor breakdown (if filtering by category)
            if filter_type == 'category':
                vendor_breakdown = conn.execute('''
                    SELECT v.name, SUM(e.amount) as total, COUNT(*) as count
                    FROM expenses e
                    JOIN vendors v ON e.vendor_id = v.id
                    WHERE e.category_id = %s AND e.date BETWEEN %s AND %s
                    GROUP BY v.id, v.name
                    ORDER BY total DESC
                    LIMIT 10
                ''', (int(filter_value), start_date, end_date)).fetchall()
    
    conn.close()
    
    return render_template('query_analysis.html',
                         filter_type=filter_type,
                         filter_value=filter_value,
                         time_period=time_period,
                         selected_month=selected_month,
                         selected_year=selected_year,
                         custom_start=custom_start,
                         custom_end=custom_end,
                         period_label=period_label,
                         start_date=start_date,
                         end_date=end_date,
                         categories=categories,
                         vendors=vendors,
                         subcategories=subcategories,
                         transactions=transactions,
                         total_amount=total_amount,
                         transaction_count=transaction_count,
                         avg_amount=avg_amount,
                         category_breakdown=category_breakdown,
                         vendor_breakdown=vendor_breakdown)


@login_required


@app.route('/query-export-pdf')
def query_export_pdf():
    """Export query results as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO
    from datetime import datetime
    import calendar
    
    # Get parameters (same as query_analysis route)
    filter_type = request.args.get('filter_type', 'category')
    filter_value = request.args.get('filter_value', '')
    time_period = request.args.get('time_period', 'month')
    selected_month = request.args.get('month', datetime.today().to_char())
    selected_year = request.args.get('year', str(datetime.today().year))
    custom_start = request.args.get('custom_start', '')
    custom_end = request.args.get('custom_end', '')
    
    # Calculate date range
    today = datetime.today()
    if time_period == 'month':
        year, month = selected_month.split('-')
        start_date = f"{year}-{month}-01"
        last_day = calendar.monthrange(int(year), int(month))[1]
        end_date = f"{year}-{month}-{last_day:02d}"
        period_label = f"{calendar.month_name[int(month)]} {year}"
    elif time_period == 'quarter':
        year = int(selected_year)
        quarter = int(request.args.get('quarter', (today.month - 1) // 3 + 1))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start_date = f"{year}-{start_month:02d}-01"
        last_day = calendar.monthrange(year, end_month)[1]
        end_date = f"{year}-{end_month:02d}-{last_day:02d}"
        period_label = f"Q{quarter} {year}"
    elif time_period == 'year':
        year = int(selected_year)
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        period_label = f"Year {year}"
    elif time_period == 'custom' and custom_start and custom_end:
        start_date = custom_start
        end_date = custom_end
        period_label = f"{start_date} to {end_date}"
    
    conn = get_db_connection()
    
    # Build query
    base_query = '''
        SELECT e.id, e.date, e.description, e.amount,
               c.name as category_name, v.name as vendor_name
        FROM expenses e
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        WHERE e.date BETWEEN %s AND %s
    '''
    
    params = [start_date, end_date]
    filter_name = ''
    
    if filter_type == 'category':
        base_query += ' AND e.category_id = %s'
        params.append(int(filter_value))
        cat = conn.execute('SELECT name FROM categories WHERE id = %s', (int(filter_value),)).fetchone()
        filter_name = cat['name'] if cat else 'Unknown'
    elif filter_type == 'vendor':
        base_query += ' AND e.vendor_id = %s'
        params.append(int(filter_value))
        vendor = conn.execute('SELECT name FROM vendors WHERE id = %s', (int(filter_value),)).fetchone()
        filter_name = vendor['name'] if vendor else 'Unknown'
    elif filter_type == 'subcategory':
        base_query += ' AND e.subcategory_id = %s'
        params.append(int(filter_value))
        subcat = conn.execute('SELECT name FROM subcategories WHERE id = %s', (int(filter_value),)).fetchone()
        filter_name = subcat['name'] if subcat else 'Unknown'
    
    base_query += ' ORDER BY e.date DESC'
    
    transactions = conn.execute(base_query, params).fetchall()
    conn.close()
    
    # Calculate stats
    total_amount = sum(t['amount'] for t in transactions)
    transaction_count = len(transactions)
    avg_amount = total_amount / transaction_count if transaction_count > 0 else 0
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.75*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("SPENDING ANALYSIS REPORT", title_style))
    elements.append(Paragraph(f"{filter_type.title()}: {filter_name}", 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=14, alignment=TA_CENTER, spaceAfter=5)))
    elements.append(Paragraph(f"{period_label}", 
                             ParagraphStyle('period', parent=styles['Normal'], 
                                          fontSize=12, alignment=TA_CENTER, spaceAfter=5)))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
                             ParagraphStyle('generated', parent=styles['Normal'], 
                                          fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=20)))
    
    # Summary box
    summary_data = [
        ['Total Amount', 'Transactions', 'Average'],
        [f'${total_amount:,.2f}', str(transaction_count), f'${avg_amount:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Transaction details
    elements.append(Paragraph("Transaction Details", 
                             ParagraphStyle('section', parent=styles['Heading2'], 
                                          fontSize=14, textColor=colors.HexColor('#495057'), spaceAfter=10)))
    
    # Build transaction table
    data = [['Date', 'Description', 'Category', 'Amount']]
    
    for txn in transactions:
        data.append([
            txn['date'],
            txn['description'][:30] + '...' if txn['description'] and len(txn['description']) > 30 else (txn['description'] or '-'),
            txn['category_name'] or '-',
            f"${txn['amount']:,.2f}"
        ])
    
    txn_table = Table(data, colWidths=[1*inch, 1.5*inch, 2.5*inch, 1*inch])
    txn_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#495057')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    
    elements.append(txn_table)
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Query_{filter_type}_{filter_name.replace(" ", "_")}_{period_label.replace(" ", "_")}.pdf'
    
    return response


@login_required


@app.route('/expenses-export-pdf')
def expenses_export_pdf():
    """Export expense report as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO
    from datetime import datetime
    
    # Get filter parameters (same as view_expenses route)
    category_id = request.args.get('category', type=int)
    subcategory_id = request.args.get('subcategory', type=int)
    vendor_id = request.args.get('vendor', type=int)
    source_id = request.args.get('source', type=int)
    period = request.args.get('period', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    search = request.args.get('search', '')
    min_amount = request.args.get('min_amount', type=float)
    max_amount = request.args.get('max_amount', type=float)
    
    # Build query
    conn = get_db_connection()
    
    query = '''
        SELECT e.id, e.date, e.description, e.amount,
               c.name as category_name, c.color as category_color,
               sc.name as subcategory_name,
               v.name as vendor_name,
               s.name as source_name
        FROM expenses e
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        LEFT JOIN sources s ON e.source_id = s.id
        WHERE 1=1
    '''
    
    params = []
    
    # Apply filters
    if category_id:
        query += ' AND e.category_id = %s'
        params.append(category_id)
    
    if subcategory_id:
        query += ' AND e.subcategory_id = %s'
        params.append(subcategory_id)
    
    if vendor_id:
        query += ' AND e.vendor_id = %s'
        params.append(vendor_id)
    
    if source_id:
        query += ' AND e.source_id = %s'
        params.append(source_id)
    
    # Search filter (description or notes)
    if search:
        query += ' AND (e.description LIKE %s OR e.notes LIKE %s)'
        search_param = f'%{search}%'
        params.append(search_param)
        params.append(search_param)
    
    # Amount range filters
    if min_amount is not None:
        query += ' AND e.amount >= %s'
        params.append(min_amount)
    
    if max_amount is not None:
        query += ' AND e.amount <= %s'
        params.append(max_amount)
    
    # Date filtering
    if period == 'mtd':
        today = datetime.today()
        start_of_month = today.replace(day=1).strftime('%Y-%m-%d')
        query += ' AND e.date >= %s'
        params.append(start_of_month)
        period_label = f"Month to Date - {today.strftime('%B %Y')}"
    elif period == 'ytd':
        today = datetime.today()
        start_of_year = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        query += ' AND e.date >= %s'
        params.append(start_of_year)
        period_label = f"Year to Date - {today.year}"
    elif period == 'custom' and start_date and end_date:
        query += ' AND e.date BETWEEN %s AND %s'
        params.append(start_date)
        params.append(end_date)
        period_label = f"{start_date} to {end_date}"
    else:
        period_label = "All Time"
    
    query += ' ORDER BY e.date DESC'
    
    expenses = conn.execute(query, params).fetchall()
    
    # Get filter names for display
    filter_desc = []
    if category_id:
        cat = conn.execute('SELECT name FROM categories WHERE id = %s', (category_id,)).fetchone()
        if cat:
            filter_desc.append(f"Category: {cat['name']}")
    
    if subcategory_id:
        subcat = conn.execute('SELECT name FROM subcategories WHERE id = %s', (subcategory_id,)).fetchone()
        if subcat:
            filter_desc.append(f"Subcategory: {subcat['name']}")
    
    if vendor_id:
        vendor = conn.execute('SELECT name FROM vendors WHERE id = %s', (vendor_id,)).fetchone()
        if vendor:
            filter_desc.append(f"Vendor: {vendor['name']}")
    
    if source_id:
        source = conn.execute('SELECT name FROM sources WHERE id = %s', (source_id,)).fetchone()
        if source:
            filter_desc.append(f"Source: {source['name']}")
    
    if search:
        filter_desc.append(f"Search: '{search}'")
    
    if min_amount is not None:
        filter_desc.append(f"Min Amount: ${min_amount:.2f}")
    
    if max_amount is not None:
        filter_desc.append(f"Max Amount: ${max_amount:.2f}")
    
    conn.close()
    
    # Calculate totals
    total_amount = sum(exp['amount'] for exp in expenses)
    expense_count = len(expenses)
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.75*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("EXPENSE REPORT", title_style))
    elements.append(Paragraph(period_label, 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=12, alignment=TA_CENTER, spaceAfter=5)))
    
    if filter_desc:
        elements.append(Paragraph(" • ".join(filter_desc), 
                                 ParagraphStyle('filters', parent=styles['Normal'], 
                                              fontSize=10, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=5)))
    
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
                             ParagraphStyle('generated', parent=styles['Normal'], 
                                          fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=15)))
    
    # Summary box
    avg_amount = total_amount / expense_count if expense_count > 0 else 0
    summary_data = [
        ['Total Expenses', 'Transactions', 'Average Amount'],
        [f'${total_amount:,.2f}', str(expense_count), f'${avg_amount:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Expense details header
    elements.append(Paragraph("Expense Details", 
                             ParagraphStyle('section', parent=styles['Heading2'], 
                                          fontSize=14, textColor=colors.HexColor('#495057'), spaceAfter=10)))
    
    # Build expense table
    data = [['Date', 'Description', 'Category', 'Vendor', 'Source', 'Amount']]
    
    for exp in expenses:
        data.append([
            exp['date'],
            exp['description'][:25] + '...' if exp['description'] and len(exp['description']) > 25 else (exp['description'] or '-'),
            exp['category_name'] or '-',
            exp['vendor_name'] or '-',
            exp['source_name'] or '-',
            f"${exp['amount']:,.2f}"
        ])
        expense_table = Table(data, colWidths=[0.9*inch, 2.0*inch, 1.0*inch, 1.1*inch,1.5*inch, 0.9*inch])
        expense_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#495057')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (5, 1), (5, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    
    elements.append(expense_table)
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Expense_Report_{datetime.now().strftime("%Y%m%d")}.pdf'
    
    return response


@login_required


@app.route('/income-export-pdf')
def income_export_pdf():
    """Export income report as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER
    from io import BytesIO
    from datetime import datetime
    import calendar
    
    # Get filter parameters (same as income route)
    period = request.args.get('period', 'all')
    category = request.args.get('category', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Build query
    conn = get_db_connection()
    
    query = '''
        SELECT date, source, description, category, amount, notes
        FROM income
        WHERE 1=1
    '''
    
    params = []
    
    # Apply filters
    if category:
        query += ' AND category = %s'
        params.append(category)
    
    # Date filtering
    today = datetime.today()
    if period == 'mtd':
        start_of_month = today.replace(day=1).strftime('%Y-%m-%d')
        query += ' AND date >= %s'
        params.append(start_of_month)
        period_label = f"Month to Date - {today.strftime('%B %Y')}"
    elif period == 'ytd':
        start_of_year = today.replace(month=1, day=1).strftime('%Y-%m-%d')
        query += ' AND date >= %s'
        params.append(start_of_year)
        period_label = f"Year to Date - {today.year}"
    elif period == 'custom' and start_date and end_date:
        query += ' AND date BETWEEN %s AND %s'
        params.append(start_date)
        params.append(end_date)
        period_label = f"{start_date} to {end_date}"
    else:
        period_label = "All Time"
    
    query += ' ORDER BY date DESC'
    
    income_records = conn.execute(query, params).fetchall()
    conn.close()
    
    # Calculate totals
    total_amount = sum(inc['amount'] for inc in income_records)
    income_count = len(income_records)
    avg_amount = total_amount / income_count if income_count > 0 else 0
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.75*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#28a745'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("INCOME REPORT", title_style))
    elements.append(Paragraph(period_label, 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=12, alignment=TA_CENTER, spaceAfter=5)))
    
    if category:
        elements.append(Paragraph(f"Category: {category}", 
                                 ParagraphStyle('filters', parent=styles['Normal'], 
                                              fontSize=10, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=5)))
    
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
                             ParagraphStyle('generated', parent=styles['Normal'], 
                                          fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=15)))
    
    # Summary box
    summary_data = [
        ['Total Income', 'Transactions', 'Average Amount'],
        [f'${total_amount:,.2f}', str(income_count), f'${avg_amount:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#28a745')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#d4edda')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 11),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Income details header
    elements.append(Paragraph("Income Details", 
                             ParagraphStyle('section', parent=styles['Heading2'], 
                                          fontSize=14, textColor=colors.HexColor('#495057'), spaceAfter=10)))
    
    # Build income table
    data = [['Date', 'Source', 'Description', 'Category', 'Amount']]
    
    for inc in income_records:
        data.append([
            inc['date'],
            inc['source'][:30] + '...' if inc['source'] and len(inc['source']) > 30 else (inc['source'] or '-'),
            inc['description'][:35] + '...' if inc['description'] and len(inc['description']) > 35 else (inc['description'] or '-'),
            inc['category'] or '-',
            f"${inc['amount']:,.2f}"
        ])
    
    income_table = Table(data, colWidths=[0.9*inch, 1.8*inch, 2.5*inch, 1.3*inch, 1.0*inch])
    income_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#495057')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    
    elements.append(income_table)
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Income_Report_{datetime.now().strftime("%Y%m%d")}.pdf'
    
    return response


@login_required


@app.route('/debt-strategy-pdf')
def debt_strategy_pdf():
    """Export complete debt payoff strategy comparison as PDF"""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from io import BytesIO
    from datetime import datetime
    
    # Get extra payment from query
    extra_payment = float(request.args.get('extra_payment', 0))
    
    conn = get_db_connection()
    debts = conn.execute('''
        SELECT * FROM debts 
        WHERE is_active = 1 
        ORDER BY current_balance ASC
    ''').fetchall()
    conn.close()
    
    if not debts:
        return "No active debts to export", 404
    
    # Calculate strategies
    strategies = calculate_payoff_strategies(debts, extra_payment)
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           rightMargin=0.5*inch, leftMargin=0.5*inch,
                           topMargin=0.75*inch, bottomMargin=0.5*inch)
    
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=22,
        textColor=colors.HexColor('#667eea'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    elements.append(Paragraph("DEBT PAYOFF STRATEGY COMPARISON", title_style))
    elements.append(Paragraph(f"Snowball vs Avalanche Methods", 
                             ParagraphStyle('subtitle', parent=styles['Normal'], 
                                          fontSize=14, alignment=TA_CENTER, spaceAfter=5)))
    if extra_payment > 0:
        elements.append(Paragraph(f"Extra Monthly Payment: ${extra_payment:,.2f}", 
                                 ParagraphStyle('extra', parent=styles['Normal'], 
                                              fontSize=12, alignment=TA_CENTER, spaceAfter=5)))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", 
                             ParagraphStyle('generated', parent=styles['Normal'], 
                                          fontSize=9, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=15)))
    
    # Comparison summary
    comparison_data = [
        ['Method', 'Total Time', 'Total Interest', 'Total Paid', 'Savings vs Other'],
        [
            '❄️ Snowball',
            f"{strategies['snowball']['months_to_payoff']} months ({strategies['snowball']['months_to_payoff']//12}y {strategies['snowball']['months_to_payoff']%12}m)",
            f"${strategies['snowball']['total_interest']:,.2f}",
            f"${strategies['snowball']['total_paid']:,.2f}",
            '-'
        ],
        [
            '🏔️ Avalanche',
            f"{strategies['avalanche']['months_to_payoff']} months ({strategies['avalanche']['months_to_payoff']//12}y {strategies['avalanche']['months_to_payoff']%12}m)",
            f"${strategies['avalanche']['total_interest']:,.2f}",
            f"${strategies['avalanche']['total_paid']:,.2f}",
            f"Save ${strategies['snowball']['total_interest'] - strategies['avalanche']['total_interest']:,.2f}"
        ]
    ]
    
    comparison_table = Table(comparison_data, colWidths=[1.5*inch, 1.8*inch, 1.5*inch, 1.5*inch, 1.8*inch])
    comparison_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e3f2fd')),
        ('BACKGROUND', (0, 2), (-1, 2), colors.HexColor('#fff3e0')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(comparison_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Snowball Method Details
    elements.append(Paragraph("❄️ SNOWBALL METHOD - Payoff Order", 
                             ParagraphStyle('section', parent=styles['Heading2'], 
                                          fontSize=14, textColor=colors.HexColor('#495057'), spaceAfter=10)))
    
    snowball_order_data = [['Order', 'Debt Name', 'Balance', 'Interest Rate', 'Min Payment']]
    for debt in strategies['snowball']['debts']:
        snowball_order_data.append([
            str(debt['order']),
            debt['name'],
            f"${debt['balance']:,.2f}",
            f"{debt['interest_rate']:.2f}%",
            f"${debt['min_payment']:,.2f}"
        ])
    
    snowball_table = Table(snowball_order_data, colWidths=[0.8*inch, 2.5*inch, 1.5*inch, 1.3*inch, 1.3*inch])
    snowball_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e3f2fd')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(snowball_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Avalanche Method Details
    elements.append(Paragraph("🏔️ AVALANCHE METHOD - Payoff Order", 
                             ParagraphStyle('section', parent=styles['Heading2'], 
                                          fontSize=14, textColor=colors.HexColor('#495057'), spaceAfter=10)))
    
    avalanche_order_data = [['Order', 'Debt Name', 'Balance', 'Interest Rate', 'Min Payment']]
    for debt in strategies['avalanche']['debts']:
        avalanche_order_data.append([
            str(debt['order']),
            debt['name'],
            f"${debt['balance']:,.2f}",
            f"{debt['interest_rate']:.2f}%",
            f"${debt['min_payment']:,.2f}"
        ])
    
    avalanche_table = Table(avalanche_order_data, colWidths=[0.8*inch, 2.5*inch, 1.5*inch, 1.3*inch, 1.3*inch])
    avalanche_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#fff3e0')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(avalanche_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Recommendation
    if strategies['snowball']['total_interest'] > strategies['avalanche']['total_interest']:
        savings = strategies['snowball']['total_interest'] - strategies['avalanche']['total_interest']
        months_faster = strategies['snowball']['months_to_payoff'] - strategies['avalanche']['months_to_payoff']
        
        rec_text = f"<b>Recommendation:</b> The Avalanche method will save you ${savings:,.2f} in interest and pay off your debts {months_faster} months faster."
    else:
        rec_text = "<b>Note:</b> Both methods result in similar outcomes for your debt portfolio."
    
    elements.append(Paragraph(rec_text, 
                             ParagraphStyle('recommendation', parent=styles['Normal'], 
                                          fontSize=11, textColor=colors.HexColor('#155724'),
                                          backColor=colors.HexColor('#d4edda'),
                                          borderPadding=10)))
    
    # Build PDF
    doc.build(elements)
    
    # Return PDF
    buffer.seek(0)
    response = make_response(buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Debt_Strategy_Comparison_{datetime.now().strftime("%Y%m%d")}.pdf'
    
    return response




# ============================================================================
# ADMIN ROUTES
# ============================================================================



@app.route('/admin')
@login_required
def admin():
    """Admin page with database management tools"""
    import os
    from datetime import datetime
    
    conn = get_db_connection()
    
    # Get statistics
    stats = {
        'expenses': conn.execute('SELECT COUNT(*) as count FROM expenses').fetchone()['count'],
        'income': conn.execute('SELECT COUNT(*) as count FROM income').fetchone()['count'],
        'categories': conn.execute('SELECT COUNT(*) as count FROM categories').fetchone()['count'],
        'subcategories': conn.execute('SELECT COUNT(*) as count FROM subcategories').fetchone()['count'],
        'vendors': conn.execute('SELECT COUNT(*) as count FROM vendors').fetchone()['count'],
        'sources': conn.execute('SELECT COUNT(*) as count FROM sources').fetchone()['count'],
        'debts': conn.execute('SELECT COUNT(*) as count FROM debts WHERE is_active = 1').fetchone()['count'],
        'debt_payments': conn.execute('SELECT COUNT(*) as count FROM debt_payments').fetchone()['count'],
    }
    
    conn.close()
    
    # Get list of backups
    backup_dir = os.path.expanduser('~/Documents/expense_tracker_backups')
    backups = []
    
    if os.path.exists(backup_dir):
        backup_folders = [d for d in os.listdir(backup_dir) if d.startswith('backup_')]
        backup_folders.sort(reverse=True)  # Most recent first
        
        for folder in backup_folders[:5]:  # Show last 5 backups
            folder_path = os.path.join(backup_dir, folder)
            if os.path.isdir(folder_path):
                # Get folder size
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(folder_path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        total_size += os.path.getsize(fp)
                
                # Format size
                size_mb = total_size / (1024 * 1024)
                size_str = f"{size_mb:.1f} MB"
                
                # Parse date from folder name (backup_YYYYMMDD_HHMMSS)
                try:
                    date_str = folder.replace('backup_', '')
                    dt = datetime.strptime(date_str, '%Y%m%d_%H%M%S')
                    date_formatted = dt.strftime('%b %d, %Y at %I:%M %p')
                except:
                    date_formatted = folder
                
                backups.append({
                    'name': folder,
                    'path': folder_path,
                    'date': date_formatted,
                    'size': size_str
                })
    
    return render_template('admin.html', stats=stats, backups=backups)



@app.route('/admin/clear-data', methods=['POST'])
@login_required
def admin_clear_data():
    """Clear data based on type"""
    try:
        data = request.get_json()
        clear_type = data.get('type')
        
        if not clear_type:
            return jsonify({'success': False, 'error': 'No type specified'})
        
        conn = get_db_connection()
        
        if clear_type == 'transactions':
            # Clear all expenses and income
            conn.execute('DELETE FROM expenses')
            conn.execute('DELETE FROM income')
            conn.commit()
            message = 'All transactions cleared'
            
        elif clear_type == 'expenses':
            # Clear only expenses
            conn.execute('DELETE FROM expenses')
            conn.commit()
            message = 'All expenses cleared'
            
        elif clear_type == 'income':
            # Clear only income
            conn.execute('DELETE FROM income')
            conn.commit()
            message = 'All income cleared'
            
        elif clear_type == 'debts':
            # Clear debt tracking data
            conn.execute('DELETE FROM debt_payments')
            conn.execute('DELETE FROM debts')
            conn.commit()
            message = 'All debt data cleared'
            
        elif clear_type == 'lists':
            # Clear categories, subcategories, vendors, sources
            conn.execute('DELETE FROM subcategories')
            conn.execute('DELETE FROM categories')
            conn.execute('DELETE FROM vendors')
            conn.execute('DELETE FROM sources')
            conn.commit()
            message = 'All lists cleared'
            
        elif clear_type == 'everything':
            # Nuclear option - clear everything
            conn.execute('DELETE FROM debt_payments')
            conn.execute('DELETE FROM debts')
            conn.execute('DELETE FROM expenses')
            conn.execute('DELETE FROM income')
            conn.execute('DELETE FROM subcategories')
            conn.execute('DELETE FROM categories')
            conn.execute('DELETE FROM income_categories')
            conn.execute('DELETE FROM vendors')
            conn.execute('DELETE FROM sources')
            conn.execute('DELETE FROM budgets')
            conn.commit()
            message = 'Everything cleared - fresh start!'
            
        else:
            conn.close()
            return jsonify({'success': False, 'error': 'Invalid clear type'})
        
        conn.close()
        return jsonify({'success': True, 'message': message})
        
    except Exception as e:
        print(f"Error clearing data: {e}")
        return jsonify({'success': False, 'error': str(e)})





@app.route('/admin/restore-backup', methods=['POST'])
@login_required
def admin_restore_backup():
    """Restore database from backup"""
    import os
    import shutil
    
    try:
        data = request.get_json()
        backup_path = data.get('path')
        
        if not backup_path:
            return jsonify({'success': False, 'error': 'No backup path specified'})
        
        # Verify backup exists
        if not os.path.exists(backup_path):
            return jsonify({'success': False, 'error': 'Backup not found'})
        
        # Path to current database
        current_db = os.path.expanduser('~/Documents/expense_tracker/expense_tracker.db')
        backup_db = os.path.join(backup_path, 'expense_tracker.db')
        
        if not os.path.exists(backup_db):
            return jsonify({'success': False, 'error': 'Database not found in backup'})
        
        # Create a backup of current state first
        emergency_backup = current_db + '.before_restore'
        shutil.copy2(current_db, emergency_backup)
        
        # Restore the backup
        shutil.copy2(backup_db, current_db)
        
        return jsonify({
            'success': True, 
            'message': f'Restored from {os.path.basename(backup_path)}'
        })
        
    except Exception as e:
        print(f"Error restoring backup: {e}")
        return jsonify({'success': False, 'error': str(e)})



# ============================================================================
# RECURRING EXPENSES
# ============================================================================

def generate_recurring_expenses(conn, recurring_id):
    """Generate future expenses for a recurring expense (next 12 months)"""
    from datetime import datetime, timedelta
    import calendar as cal_module
    
    recurring = conn.execute('SELECT * FROM recurring_expenses WHERE id = %s', (recurring_id,)).fetchone()
    if not recurring or not recurring['is_active']:
        print(f"  Recurring {recurring_id} not found or inactive")
        return
    
    start_date = datetime.strptime(recurring['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(recurring['end_date'], '%Y-%m-%d') if recurring['end_date'] else None
    
    today = datetime.now()
    max_date = today + timedelta(days=365)
    if end_date and end_date < max_date:
        max_date = end_date
    
    generated_dates = []
    
    if recurring['frequency'] in ('weekly', 'biweekly'):
        target_day = recurring['day_of_week'] if recurring['day_of_week'] is not None else start_date.weekday()
        
        current = start_date
        days_ahead = target_day - current.weekday()
        if days_ahead < 0:
            days_ahead += 7
        current = current + timedelta(days=days_ahead)
        
        # Skip the first occurrence (already added as the main expense)
        step = 1 if recurring['frequency'] == 'weekly' else 2
        current = current + timedelta(weeks=step)
        
        while current <= max_date:
            generated_dates.append(current)
            current += timedelta(weeks=step)
    
    elif recurring['frequency'] == 'monthly_date':
        target_day = recurring['day_of_month'] if recurring['day_of_month'] else 1
        
        year = start_date.year
        month = start_date.month + 1
        if month > 12:
            month = 1
            year += 1
        
        while True:
            max_day = cal_module.monthrange(year, month)[1]
            actual_day = min(target_day, max_day)
            gen_date = datetime(year, month, actual_day)
            if gen_date > max_date:
                break
            generated_dates.append(gen_date)
            month += 1
            if month > 12:
                month = 1
                year += 1
    
    elif recurring['frequency'] == 'monthly_day':
        target_weekday = recurring['day_of_week'] if recurring['day_of_week'] is not None else 4
        occurrence = recurring['day_of_month'] if recurring['day_of_month'] else 1
        
        year = start_date.year
        month = start_date.month + 1
        if month > 12:
            month = 1
            year += 1
        
        while True:
            gen_date = get_nth_weekday(year, month, target_weekday, occurrence)
            if gen_date is None or gen_date > max_date:
                break
            generated_dates.append(gen_date)
            month += 1
            if month > 12:
                month = 1
                year += 1
    
    print(f"  Generating {len(generated_dates)} future expenses for recurring {recurring_id}")
    
    for gen_date in generated_dates:
        existing = conn.execute(
            'SELECT id FROM expenses WHERE recurring_id = %s AND date = %s',
            (recurring_id, gen_date.strftime('%Y-%m-%d'))
        ).fetchone()
        
        if not existing:
            conn.execute('''
                INSERT INTO expenses (date, source_id, description, category_id,
                    subcategory_id, vendor_id, amount, notes, recurring_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (gen_date.strftime('%Y-%m-%d'), recurring['source_id'],
                  recurring['description'], recurring['category_id'],
                  recurring['subcategory_id'], recurring['vendor_id'],
                  recurring['amount'], recurring['notes'], recurring_id))


def get_nth_weekday(year, month, weekday, n):
    """Get the nth occurrence of a weekday in a month. weekday: 0=Mon, 6=Sun"""
    from datetime import datetime
    import calendar as cal_module
    
    cal = cal_module.monthcalendar(year, month)
    count = 0
    for week in cal:
        if week[weekday] != 0:
            count += 1
            if count == n:
                return datetime(year, month, week[weekday])
    return None




@app.route('/api/check-duplicate', methods=['POST'])
@login_required
def check_duplicate():
    """Check if an expense might be a duplicate"""
    try:
        data = request.get_json()
        date = data.get('date')
        amount = data.get('amount')
        category_id = data.get('category_id')
        
        conn = get_db_connection()
        
        duplicates = conn.execute('''
            SELECT e.id, e.date, e.description, e.amount,
                   c.name as category_name,
                   CASE WHEN e.recurring_id IS NOT NULL THEN 1 ELSE 0 END as is_recurring
            FROM expenses e
            LEFT JOIN categories c ON e.category_id = c.id
            WHERE e.date = %s AND e.amount = %s AND e.category_id = %s
        ''', (date, amount, category_id)).fetchall()
        
        conn.close()
        
        results = []
        for dup in duplicates:
            results.append({
                'id': dup['id'],
                'date': dup['date'],
                'description': dup['description'],
                'amount': dup['amount'],
                'category': dup['category_name'],
                'is_recurring': bool(dup['is_recurring'])
            })
        
        return jsonify({'duplicates': results})
    except Exception as e:
        print(f"Error checking duplicates: {e}")
        return jsonify({'duplicates': []})




@app.route('/recurring')
@login_required
def manage_recurring():
    """Manage recurring expenses and income page"""
    conn = get_db_connection()
    
    # Fetch recurring expenses
    recurring_expenses = conn.execute('''
        SELECT r.*,
               c.name as category_name, c.color as category_color,
               sc.name as subcategory_name,
               v.name as vendor_name,
               s.name as source_name,
               (SELECT COUNT(*) FROM expenses e WHERE e.recurring_id = r.id) as generated_count
        FROM recurring_expenses r
        LEFT JOIN categories c ON r.category_id = c.id
        LEFT JOIN subcategories sc ON r.subcategory_id = sc.id
        LEFT JOIN vendors v ON r.vendor_id = v.id
        LEFT JOIN sources s ON r.source_id = s.id
        ORDER BY r.is_active DESC, r.description
    ''').fetchall()
    
    # Fetch recurring income
    recurring_income = conn.execute('''
        SELECT r.*,
               (SELECT COUNT(*) FROM income i WHERE i.recurring_id = r.id) as generated_count
        FROM recurring_income r
        ORDER BY r.is_active DESC, r.description
    ''').fetchall()
    
    conn.close()
    return render_template('manage_recurring.html', 
                         recurring_expenses=recurring_expenses,
                         recurring_income=recurring_income)




@app.route('/recurring/cancel/<int:recurring_id>', methods=['POST'])
@login_required
def cancel_recurring(recurring_id):
    """Cancel a recurring expense"""
    conn = get_db_connection()
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    
    conn.execute('UPDATE recurring_expenses SET is_active = 0 WHERE id = %s', (recurring_id,))
    conn.execute('DELETE FROM expenses WHERE recurring_id = %s AND date > %s', (recurring_id, today))
    
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




@app.route('/recurring/reactivate/<int:recurring_id>', methods=['POST'])
@login_required
def reactivate_recurring(recurring_id):
    """Reactivate a cancelled recurring expense"""
    conn = get_db_connection()
    conn.execute('UPDATE recurring_expenses SET is_active = 1 WHERE id = %s', (recurring_id,))
    generate_recurring_expenses(conn, recurring_id)
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




@app.route('/recurring/delete/<int:recurring_id>', methods=['POST'])
@login_required
def delete_recurring(recurring_id):
    """Delete a recurring expense and all generated expenses"""
    conn = get_db_connection()
    conn.execute('DELETE FROM expenses WHERE recurring_id = %s', (recurring_id,))
    conn.execute('DELETE FROM recurring_expenses WHERE id = %s', (recurring_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




def generate_recurring_income(conn, recurring_id):
    """Generate future income entries for a recurring income (next 12 months)"""
    from datetime import datetime, timedelta
    import calendar as cal_module
    
    recurring = conn.execute('SELECT * FROM recurring_income WHERE id = %s', (recurring_id,)).fetchone()
    if not recurring or not recurring['is_active']:
        print(f"  Recurring income {recurring_id} not found or inactive")
        return
    
    start_date = datetime.strptime(recurring['start_date'], '%Y-%m-%d')
    end_date = datetime.strptime(recurring['end_date'], '%Y-%m-%d') if recurring['end_date'] else None
    
    today = datetime.now()
    max_date = today + timedelta(days=365)
    if end_date and end_date < max_date:
        max_date = end_date
    
    generated_dates = []
    
    if recurring['frequency'] in ('weekly', 'biweekly'):
        target_day = recurring['day_of_week'] if recurring['day_of_week'] is not None else start_date.weekday()
        
        current = start_date
        days_ahead = target_day - current.weekday()
        if days_ahead < 0:
            days_ahead += 7
        current = current + timedelta(days=days_ahead)
        
        step = 1 if recurring['frequency'] == 'weekly' else 2
        current = current + timedelta(weeks=step)
        
        while current <= max_date:
            generated_dates.append(current)
            current += timedelta(weeks=step)
    
    elif recurring['frequency'] == 'monthly_date':
        target_day = recurring['day_of_month'] if recurring['day_of_month'] else 1
        
        year = start_date.year
        month = start_date.month + 1
        if month > 12:
            month = 1
            year += 1
        
        while True:
            max_day = cal_module.monthrange(year, month)[1]
            actual_day = min(target_day, max_day)
            gen_date = datetime(year, month, actual_day)
            if gen_date > max_date:
                break
            generated_dates.append(gen_date)
            month += 1
            if month > 12:
                month = 1
                year += 1
    
    elif recurring['frequency'] == 'monthly_day':
        target_weekday = recurring['day_of_week'] if recurring['day_of_week'] is not None else 4
        occurrence = recurring['day_of_month'] if recurring['day_of_month'] else 1
        
        year = start_date.year
        month = start_date.month + 1
        if month > 12:
            month = 1
            year += 1
        
        while True:
            gen_date = get_nth_weekday(year, month, target_weekday, occurrence)
            if gen_date is None or gen_date > max_date:
                break
            generated_dates.append(gen_date)
            month += 1
            if month > 12:
                month = 1
                year += 1
    
    elif recurring['frequency'] == 'yearly':
        # Yearly on the same date
        target_month = start_date.month
        target_day = start_date.day
        
        year = start_date.year + 1  # Start from next year
        
        while True:
            try:
                gen_date = datetime(year, target_month, target_day)
            except ValueError:
                # Handle Feb 29 on non-leap years
                if target_month == 2 and target_day == 29:
                    gen_date = datetime(year, 2, 28)
                else:
                    break
            
            if gen_date > max_date:
                break
            
            generated_dates.append(gen_date)
            year += 1
    
    print(f"  Generating {len(generated_dates)} future income entries for recurring {recurring_id}")
    
    for gen_date in generated_dates:
        existing = conn.execute(
            'SELECT id FROM income WHERE recurring_id = %s AND date = %s',
            (recurring_id, gen_date.strftime('%Y-%m-%d'))
        ).fetchone()
        
        if not existing:
            conn.execute('''
                INSERT INTO income (date, source, description, category, amount, notes, recurring_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (gen_date.strftime('%Y-%m-%d'), recurring['source'],
                  recurring['description'], recurring['category'],
                  recurring['amount'], recurring['notes'], recurring_id))




@app.route('/recurring/income/cancel/<int:recurring_id>', methods=['POST'])
@login_required
def cancel_recurring_income(recurring_id):
    """Cancel a recurring income"""
    conn = get_db_connection()
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    
    conn.execute('UPDATE recurring_income SET is_active = 0 WHERE id = %s', (recurring_id,))
    conn.execute('DELETE FROM income WHERE recurring_id = %s AND date > %s', (recurring_id, today))
    
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




@app.route('/recurring/income/reactivate/<int:recurring_id>', methods=['POST'])
@login_required
def reactivate_recurring_income(recurring_id):
    """Reactivate a cancelled recurring income"""
    conn = get_db_connection()
    conn.execute('UPDATE recurring_income SET is_active = 1 WHERE id = %s', (recurring_id,))
    generate_recurring_income(conn, recurring_id)
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




@app.route('/recurring/income/delete/<int:recurring_id>', methods=['POST'])
@login_required
def delete_recurring_income(recurring_id):
    """Delete a recurring income and all generated entries"""
    conn = get_db_connection()
    conn.execute('DELETE FROM income WHERE recurring_id = %s', (recurring_id,))
    conn.execute('DELETE FROM recurring_income WHERE id = %s', (recurring_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('manage_recurring'))




def calculate_fixed_payment_schedules(debts):
    """Calculate month-by-month payment schedules for excluded (fixed payment) debts"""
    schedules = []
    
    for debt in debts:
        balance = debt['current_balance']
        monthly_rate = debt['interest_rate'] / 100 / 12
        min_payment = debt['minimum_payment']
        
        if balance <= 0:
            continue
        
        schedule = {
            'debt_id': debt['id'],
            'debt_name': debt['name'],
            'starting_balance': balance,
            'interest_rate': debt['interest_rate'],
            'monthly_payment': min_payment,
            'timeline': [],
            'total_interest': 0,
            'months_to_payoff': 0
        }
        
        month = 1
        max_months = 600  # Safety limit (50 years)
        
        while balance > 0.01 and month <= max_months:
            # Calculate interest for this month
            interest = balance * monthly_rate
            
            # Principal is payment minus interest
            principal = min_payment - interest
            
            # If payment doesn't cover interest, debt will never be paid off
            if principal <= 0:
                schedule['error'] = 'Payment does not cover interest. Debt cannot be paid off.'
                break
            
            # Don't overpay on final payment
            if balance < min_payment:
                principal = balance
                interest = 0
                payment = balance
            else:
                payment = min_payment
            
            # Update balance
            balance -= principal
            
            # Record this month
            schedule['timeline'].append({
                'month': month,
                'payment': payment,
                'interest': interest,
                'principal': principal,
                'balance': max(0, balance)
            })
            
            schedule['total_interest'] += interest
            month += 1
        
        schedule['months_to_payoff'] = len(schedule['timeline'])
        schedules.append(schedule)
    
    return schedules






@app.route('/debt/toggle-strategy/<int:debt_id>', methods=['POST'])
@login_required
def toggle_debt_strategy(debt_id):
    """Toggle whether a debt is included in payoff strategies"""
    conn = get_db_connection()
    
    debt = conn.execute('SELECT include_in_strategy FROM debts WHERE id = %s', (debt_id,)).fetchone()
    
    if debt:
        new_value = 0 if debt['include_in_strategy'] else 1
        conn.execute('UPDATE debts SET include_in_strategy = %s WHERE id = %s', (new_value, debt_id))
        conn.commit()
    
    conn.close()
    return redirect(url_for('debt_payoff'))




def calculate_fixed_payment_schedules(debts):
    """Calculate month-by-month payment schedules for excluded (fixed payment) debts"""
    schedules = []
    
    for debt in debts:
        balance = debt['current_balance']
        monthly_rate = debt['interest_rate'] / 100 / 12
        min_payment = debt['minimum_payment']
        
        if balance <= 0:
            continue
        
        schedule = {
            'debt_id': debt['id'],
            'debt_name': debt['name'],
            'starting_balance': balance,
            'interest_rate': debt['interest_rate'],
            'monthly_payment': min_payment,
            'timeline': [],
            'total_interest': 0,
            'months_to_payoff': 0
        }
        
        month = 1
        max_months = 600  # Safety limit (50 years)
        
        while balance > 0.01 and month <= max_months:
            # Calculate interest for this month
            interest = balance * monthly_rate
            
            # Principal is payment minus interest
            principal = min_payment - interest
            
            # If payment doesn't cover interest, debt will never be paid off
            if principal <= 0:
                schedule['error'] = 'Payment does not cover interest. Debt cannot be paid off.'
                break
            
            # Don't overpay on final payment
            if balance < min_payment:
                principal = balance
                interest = 0
                payment = balance
            else:
                payment = min_payment
            
            # Update balance
            balance -= principal
            
            # Record this month
            schedule['timeline'].append({
                'month': month,
                'payment': payment,
                'interest': interest,
                'principal': principal,
                'balance': max(0, balance)
            })
            
            schedule['total_interest'] += interest
            month += 1
        
        schedule['months_to_payoff'] = len(schedule['timeline'])
        schedules.append(schedule)
    
    return schedules






@app.route('/api/subcategories')
def api_subcategories():
    """Get subcategories for a category"""
    category_id = request.args.get('category_id')
    
    if not category_id:
        return jsonify({'subcategories': []})
    
    conn = get_db_connection()
    subcategories = conn.execute(
        'SELECT id, name FROM subcategories WHERE category_id = %s ORDER BY name',
        (category_id,)
    ).fetchall()
    conn.close()
    
    return jsonify({
        'subcategories': [{'id': s['id'], 'name': s['name']} for s in subcategories]
    })






@app.route('/help')
@login_required
def help_page():
    """Help & Training page"""
    conn = get_db_connection()
    
    # Get all sections with their items
    sections = conn.execute(
        'SELECT * FROM help_sections WHERE is_active = 1 ORDER BY display_order'
    ).fetchall()
    
    sections_with_items = []
    for section in sections:
        items = conn.execute(
            'SELECT * FROM help_items WHERE section_id = %s AND is_active = 1 ORDER BY display_order',
            (section['id'],)
        ).fetchall()
        sections_with_items.append({
            'section': section,
            'items': items
        })
    
    conn.close()
    return render_template('help.html', sections_with_items=sections_with_items)






@app.route('/help/edit-item/<int:item_id>', methods=['GET', 'POST'])
@login_required
def edit_help_item(item_id):
    """Edit a help item"""
    conn = get_db_connection()
    
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        # Handle image upload
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename:
                import os
                from werkzeug.utils import secure_filename
                
                upload_folder = os.path.join('static', 'help_images')
                os.makedirs(upload_folder, exist_ok=True)
                
                filename = secure_filename(file.filename)
                from datetime import datetime
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{filename}"
                
                filepath = os.path.join(upload_folder, filename)
                file.save(filepath)
                image_path = f"help_images/{filename}"
        
        # Update item
        if image_path:
            conn.execute(
                'UPDATE help_items SET title = %s, content = %s, image_path = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                (title, content, image_path, item_id)
            )
        else:
            conn.execute(
                'UPDATE help_items SET title = %s, content = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s',
                (title, content, item_id)
            )
        
        conn.commit()
        conn.close()
        return redirect(url_for('help_page'))
    
    # GET
    item = conn.execute('SELECT * FROM help_items WHERE id = %s', (item_id,)).fetchone()
    conn.close()
    
    if not item:
        return redirect(url_for('help_page'))
    
    return render_template('edit_help_item.html', item=item)




@app.route('/help/delete-item-image/<int:item_id>', methods=['POST'])
@login_required
def delete_help_item_image(item_id):
    """Delete image from help item"""
    conn = get_db_connection()
    
    item = conn.execute('SELECT image_path FROM help_items WHERE id = %s', (item_id,)).fetchone()
    
    if item and item['image_path']:
        import os
        filepath = os.path.join('static', item['image_path'])
        if os.path.exists(filepath):
            os.remove(filepath)
        
        conn.execute('UPDATE help_items SET image_path = NULL WHERE id = %s', (item_id,))
        conn.commit()
    
    conn.close()
    return redirect(url_for('edit_help_item', item_id=item_id))




@app.route('/help/edit/<section_key>', methods=['GET', 'POST'])
@login_required
def edit_help_section_old(section_key):
    pass





@app.route('/paycheck-planner', methods=['GET', 'POST'])
@login_required
def paycheck_planner():
    """Paycheck planner - cash flow between paychecks"""
    from datetime import datetime, timedelta
    import calendar as cal_module
    
    conn = get_db_connection()
    
    # Handle payday schedule update
    if request.method == 'POST' and 'schedule_frequency' in request.form:
        frequency = request.form.get('schedule_frequency')
        day_of_week = request.form.get('schedule_day_of_week', type=int)
        day_of_month = request.form.get('schedule_day_of_month', type=int)
        last_payday = request.form.get('last_payday')
        
        # Update or insert schedule
        conn.execute('DELETE FROM payday_schedule')
        conn.execute(
            'INSERT INTO payday_schedule (id, frequency, day_of_week, day_of_month, last_payday) VALUES (1, %s, %s, %s, %s)',
            (frequency, day_of_week, day_of_month, last_payday)
        )
        conn.commit()
    
    # Get parameters first (needed for all operations)
    if request.method == 'POST':
        paycheck_date = request.form.get('paycheck_date')
        paycheck_amount = float(request.form.get('paycheck_amount', 0)) if request.form.get('paycheck_amount') else 0
    else:
        paycheck_date = request.args.get('paycheck_date')
        paycheck_amount = float(request.args.get('paycheck_amount', 0)) if request.args.get('paycheck_amount') else 0
    
    # Handle estimated expense add/delete
    if request.method == 'POST' and 'add_estimate' in request.form:
        description = request.form.get('estimate_description')
        category_id = request.form.get('estimate_category') or None
        subcategory_id = request.form.get('estimate_subcategory') or None
        vendor_id = request.form.get('estimate_vendor') or None
        amount = float(request.form.get('estimate_amount', 0))
        
        conn.execute(
            'INSERT INTO estimated_expenses (paycheck_date, description, category_id, subcategory_id, vendor_id, amount) VALUES (%s, %s, %s, %s, %s, %s)',
            (paycheck_date, description, category_id, subcategory_id, vendor_id, amount)
        )
        conn.commit()
    
    if request.method == 'POST' and 'delete_estimate' in request.form:
        estimate_id = request.form.get('delete_estimate')
        conn.execute('DELETE FROM estimated_expenses WHERE id = %s', (estimate_id,))
        conn.commit()
    
    # Get active recurring income for dropdown
    recurring_income = conn.execute(
        'SELECT * FROM recurring_income WHERE is_active = 1 ORDER BY description'
    ).fetchall()
    
    # If no paycheck date provided, try to calculate next paycheck from recurring income
    if not paycheck_date and recurring_income:
        # Use first recurring income to calculate next date
        first_income = recurring_income[0]
        today = datetime.now().date()
        
        # Calculate next occurrence
        next_date = calculate_next_recurring_date(first_income, today)
        if next_date:
            paycheck_date = next_date.strftime('%Y-%m-%d')
            paycheck_amount = first_income['amount']
    
    # If still no paycheck_date, default to 2 weeks from today
    if not paycheck_date:
        default_date = datetime.now().date() + timedelta(days=14)
        paycheck_date = default_date.strftime('%Y-%m-%d')
    
    # Get all recurring expenses between now and paycheck date
    today = datetime.now().date()
    paycheck_dt = datetime.strptime(paycheck_date, '%Y-%m-%d').date()
    
    recurring_expenses = conn.execute(
        'SELECT * FROM recurring_expenses WHERE is_active = 1'
    ).fetchall()
    
    # Calculate which expenses occur between now and paycheck
    bills_due = []
    for expense in recurring_expenses:
        # Get all generated expenses for this recurring expense between now and paycheck
        generated = conn.execute(
            'SELECT * FROM expenses WHERE recurring_id = %s AND date >= %s AND date <= %s ORDER BY date',
            (expense['id'], today.strftime('%Y-%m-%d'), paycheck_date)
        ).fetchall()
        
        for gen in generated:
            bills_due.append({
                'date': gen['date'],
                'description': expense['description'],
                'amount': expense['amount'],
                'category_id': expense['category_id']
            })
    
    # Get category names
    for bill in bills_due:
        cat = conn.execute('SELECT name FROM categories WHERE id = %s', (bill['category_id'],)).fetchone()
        bill['category'] = cat['name'] if cat else 'Unknown'
    
    # Sort by date
    bills_due.sort(key=lambda x: x['date'])
    
    # Get estimated expenses for this paycheck period
    estimated_expenses = []
    if paycheck_date:
        estimates = conn.execute(
            'SELECT e.*, c.name as category_name, sc.name as subcategory_name, v.name as vendor_name FROM estimated_expenses e LEFT JOIN categories c ON e.category_id = c.id LEFT JOIN subcategories sc ON e.subcategory_id = sc.id LEFT JOIN vendors v ON e.vendor_id = v.id WHERE e.paycheck_date = %s ORDER BY e.created_at',
            (paycheck_date,)
        ).fetchall()
        estimated_expenses = [dict(e) for e in estimates]
    
    # Get categories, subcategories, vendors for form
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    subcategories = conn.execute('SELECT * FROM subcategories ORDER BY name').fetchall()
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    
    # Get payday schedule
    schedule = conn.execute('SELECT * FROM payday_schedule WHERE id = 1').fetchone()
    
    # Calculate next payday from schedule
    next_scheduled_payday = None
    if schedule and not paycheck_date:
        from datetime import datetime, timedelta
        import calendar as cal_module
        
        today = datetime.now().date()
        last_payday = datetime.strptime(schedule['last_payday'], '%Y-%m-%d').date() if schedule['last_payday'] else today
        
        if schedule['frequency'] == 'weekly':
            days_ahead = 7
            next_scheduled_payday = last_payday + timedelta(days=days_ahead)
            while next_scheduled_payday <= today:
                next_scheduled_payday += timedelta(days=7)
        elif schedule['frequency'] == 'biweekly':
            days_ahead = 14
            next_scheduled_payday = last_payday + timedelta(days=days_ahead)
            while next_scheduled_payday <= today:
                next_scheduled_payday += timedelta(days=14)
        elif schedule['frequency'] == 'monthly':
            # Use day_of_month
            day = schedule['day_of_month'] or 1
            year = today.year
            month = today.month
            if today.day >= day:
                month += 1
                if month > 12:
                    month = 1
                    year += 1
            max_day = cal_module.monthrange(year, month)[1]
            next_scheduled_payday = datetime(year, month, min(day, max_day)).date()
        
        if next_scheduled_payday:
            paycheck_date = next_scheduled_payday.strftime('%Y-%m-%d')
    
    # Calculate totals
    total_bills = sum(bill['amount'] for bill in bills_due)
    total_estimates = sum(e['amount'] for e in estimated_expenses)
    money_left = paycheck_amount - total_bills - total_estimates
    
    conn.close()
    
    return render_template('paycheck_planner.html',
                         paycheck_date=paycheck_date,
                         paycheck_amount=paycheck_amount,
                         recurring_income=recurring_income,
                         bills_due=bills_due,
                         estimated_expenses=estimated_expenses,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         schedule=schedule,
                         total_bills=total_bills,
                         total_estimates=total_estimates,
                         money_left=money_left)


def calculate_next_recurring_date(recurring_item, from_date):
    """Calculate next occurrence of a recurring item from a given date"""
    from datetime import datetime, timedelta
    import calendar as cal_module
    
    start_date = datetime.strptime(recurring_item['start_date'], '%Y-%m-%d').date()
    frequency = recurring_item['frequency']
    
    if frequency == 'weekly':
        target_day = recurring_item['day_of_week'] if recurring_item['day_of_week'] is not None else start_date.weekday()
        current = from_date
        days_ahead = target_day - current.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return current + timedelta(days=days_ahead)
    
    elif frequency == 'biweekly':
        target_day = recurring_item['day_of_week'] if recurring_item['day_of_week'] is not None else start_date.weekday()
        current = from_date
        days_ahead = target_day - current.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_date = current + timedelta(days=days_ahead)
        
        # Check if this is the right biweekly occurrence
        # Calculate weeks between start_date and next_date
        weeks_diff = (next_date - start_date).days // 7
        if weeks_diff % 2 != 0:
            next_date += timedelta(weeks=1)
        return next_date
    
    elif frequency == 'monthly_date':
        target_day = recurring_item['day_of_month'] if recurring_item['day_of_month'] else 1
        year = from_date.year
        month = from_date.month
        
        # Try this month
        max_day = cal_module.monthrange(year, month)[1]
        actual_day = min(target_day, max_day)
        try:
            next_date = from_date.replace(day=actual_day)
            if next_date <= from_date:
                # Move to next month
                if month == 12:
                    year += 1
                    month = 1
                else:
                    month += 1
                max_day = cal_module.monthrange(year, month)[1]
                actual_day = min(target_day, max_day)
                next_date = datetime(year, month, actual_day).date()
            return next_date
        except ValueError:
            return None
    
    elif frequency == 'yearly':
        # Yearly on the same date
        target_month = start_date.month
        target_day = start_date.day
        
        # Start from current year
        year = from_date.year
        
        # Try this year first
        try:
            next_date = datetime(year, target_month, target_day).date()
            if next_date <= from_date:
                # Already passed this year, try next year
                year += 1
                try:
                    next_date = datetime(year, target_month, target_day).date()
                except ValueError:
                    # Handle Feb 29 on non-leap year
                    if target_month == 2 and target_day == 29:
                        next_date = datetime(year, 2, 28).date()
                    else:
                        return None
            return next_date
        except ValueError:
            # Handle Feb 29 on non-leap year
            if target_month == 2 and target_day == 29:
                next_date = datetime(year, 2, 28).date()
                if next_date <= from_date:
                    year += 1
                    next_date = datetime(year, 2, 28).date()
                return next_date
            else:
                return None
    
    return None








@app.route('/paycheck-planner/pdf')
@login_required
def paycheck_planner_pdf():
    """Export paycheck plan to PDF"""
    from datetime import datetime
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    
    # Get parameters
    paycheck_date = request.args.get('paycheck_date')
    paycheck_amount = float(request.args.get('paycheck_amount', 0))
    
    if not paycheck_date or not paycheck_amount:
        return redirect(url_for('paycheck_planner'))
    
    conn = get_db_connection()
    
    # Get recurring bills
    today = datetime.now().date()
    paycheck_dt = datetime.strptime(paycheck_date, '%Y-%m-%d').date()
    
    recurring_expenses = conn.execute(
        'SELECT * FROM recurring_expenses WHERE is_active = 1'
    ).fetchall()
    
    bills_due = []
    for expense in recurring_expenses:
        generated = conn.execute(
            'SELECT * FROM expenses WHERE recurring_id = %s AND date >= %s AND date <= %s ORDER BY date',
            (expense['id'], today.strftime('%Y-%m-%d'), paycheck_date)
        ).fetchall()
        
        for gen in generated:
            cat = conn.execute('SELECT name FROM categories WHERE id = %s', (expense['category_id'],)).fetchone()
            bills_due.append({
                'date': gen['date'],
                'description': expense['description'],
                'amount': expense['amount'],
                'category': cat['name'] if cat else 'Unknown'
            })
    
    bills_due.sort(key=lambda x: x['date'])
    
    # Get estimated expenses
    estimates = conn.execute(
        'SELECT e.*, c.name as category_name, sc.name as subcategory_name FROM estimated_expenses e LEFT JOIN categories c ON e.category_id = c.id LEFT JOIN subcategories sc ON e.subcategory_id = sc.id WHERE e.paycheck_date = %s ORDER BY e.created_at',
        (paycheck_date,)
    ).fetchall()
    
    conn.close()
    
    # Calculate totals
    total_bills = sum(bill['amount'] for bill in bills_due)
    total_estimates = sum(e['amount'] for e in estimates)
    money_left = paycheck_amount - total_bills - total_estimates
    
    # Create PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=24, textColor=colors.HexColor('#667eea'), spaceAfter=20, alignment=TA_CENTER)
    elements.append(Paragraph('💰 Paycheck Planner', title_style))
    elements.append(Paragraph(f'Paycheck Date: {paycheck_date}', styles['Normal']))
    elements.append(Spacer(1, 20))
    
    # Summary table
    summary_data = [
        ['Paycheck', f'${paycheck_amount:.2f}'],
        ['Recurring Bills', f'-${total_bills:.2f}'],
        ['Estimated Expenses', f'-${total_estimates:.2f}'],
        ['Money Left', f'${money_left:.2f}']
    ]
    summary_table = Table(summary_data, colWidths=[3*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#4facfe') if money_left >= 0 else colors.HexColor('#fa709a')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('PADDING', (0, 0), (-1, -1), 12),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 30))
    
    # Recurring Bills
    if bills_due:
        elements.append(Paragraph('📋 Recurring Bills', styles['Heading2']))
        elements.append(Spacer(1, 10))
        bills_data = [['Date', 'Description', 'Category', 'Amount']]
        for bill in bills_due:
            bills_data.append([bill['date'], bill['description'], bill['category'], f'-${bill["amount"]:.2f}'])
        bills_data.append(['', '', 'Total', f'-${total_bills:.2f}'])
        
        bills_table = Table(bills_data, colWidths=[1*inch, 2.5*inch, 1.5*inch, 1*inch])
        bills_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(bills_table)
        elements.append(Spacer(1, 20))
    
    # Estimated Expenses
    if estimates:
        elements.append(Paragraph('📝 Estimated Expenses', styles['Heading2']))
        elements.append(Spacer(1, 10))
        est_data = [['Description', 'Category', 'Amount']]
        for est in estimates:
            cat_text = est['category_name'] or ''
            if est['subcategory_name']:
                cat_text += f' › {est["subcategory_name"]}'
            est_data.append([est['description'], cat_text, f'-${est["amount"]:.2f}'])
        est_data.append(['', 'Total', f'-${total_estimates:.2f}'])
        
        est_table = Table(est_data, colWidths=[2.5*inch, 2.5*inch, 1*inch])
        est_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        elements.append(est_table)
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(buffer, as_attachment=True, download_name=f'paycheck_plan_{paycheck_date}.pdf', mimetype='application/pdf')






@app.route('/import-csv', methods=['GET', 'POST'])
@login_required
def import_csv():
    """Simple CSV import - upload and map columns"""
    import csv
    import io
    
    conn = get_db_connection()
    sources = conn.execute('SELECT * FROM sources ORDER BY name').fetchall()
    
    if request.method == 'POST' and 'csv_file' in request.files:
        file = request.files['csv_file']
        
        if file and file.filename.endswith('.csv'):
            # Read CSV
            csv_text = file.stream.read().decode('UTF-8')
            stream = io.StringIO(csv_text, newline=None)
            
            # Try to detect if first line is header or data
            first_line = csv_text.split('\n')[0] if csv_text else ''
            first_col = first_line.split(',')[0].strip() if ',' in first_line else ''
            
            # If first column looks like a date, it's data not header
            has_header = True
            if len(first_col) == 10 and first_col[4] == '-' and first_col[7] == '-':
                has_header = False
            
            if has_header:
                # CSV has headers - use them
                stream.seek(0)
                csv_reader = csv.DictReader(stream)
                columns = list(csv_reader.fieldnames)
            else:
                # No headers - generate column names
                stream.seek(0)
                reader = csv.reader(stream)
                first_row = next(reader, None)
                num_cols = len(first_row) if first_row else 0
                columns = [f'Column {i+1}' for i in range(num_cols)]
            
            # Get preview rows (first 5)
            stream.seek(0)
            if has_header:
                csv_reader = csv.DictReader(stream)
            else:
                # Add generated headers
                header_line = ','.join(columns) + '\n'
                stream = io.StringIO(header_line + csv_text)
                csv_reader = csv.DictReader(stream)
            
            preview_rows = []
            for i, row in enumerate(csv_reader):
                if i >= 5:
                    break
                preview_rows.append(row)
            
            # Store CSV in temp file (session cookies have 4KB limit!)
            import tempfile
            import uuid
            
            if not has_header:
                csv_text = ','.join(columns) + '\n' + csv_text
            
            # Create temp file
            temp_id = str(uuid.uuid4())
            temp_dir = os.path.join(os.path.expanduser('~/Documents/expense_tracker'), 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            temp_path = os.path.join(temp_dir, f'{temp_id}.csv')
            
            with open(temp_path, 'w') as f:
                f.write(csv_text)
            
            session['csv_temp_id'] = temp_id
            session['csv_filename'] = file.filename
            
            conn.close()
            return render_template('csv_import.html',
                                 columns=columns,
                                 preview_rows=preview_rows,
                                 sources=sources)
    
    conn.close()
    return render_template('csv_import.html', sources=sources)




@app.route('/import-csv/process', methods=['POST'])
@login_required
def process_csv_import():
    """Process CSV and import expenses"""
    import csv
    import io
    import base64
    from datetime import datetime
    
    # Get form data
    date_column = request.form.get('date_column')
    amount_column = request.form.get('amount_column')
    income_column = request.form.get('income_column')  # Optional income column
    description_column = request.form.get('description_column')
    default_source_id = request.form.get('default_source_id')
    
    # Get CSV from temp file
    temp_id = session.get('csv_temp_id')
    if not temp_id:
        return redirect(url_for('import_csv', error='CSV data not found'))
    
    temp_dir = os.path.join(os.path.expanduser('~/Documents/expense_tracker'), 'temp')
    temp_path = os.path.join(temp_dir, f'{temp_id}.csv')
    
    if not os.path.exists(temp_path):
        return redirect(url_for('import_csv', error='CSV file expired'))
    
    with open(temp_path, 'r') as f:
        csv_text = f.read()
    
    print(f"DEBUG: CSV text length: {len(csv_text)}")
    print(f"DEBUG: First 200 chars: {csv_text[:200]}")
    print(f"DEBUG: Date column: {date_column}")
    print(f"DEBUG: Amount column: {amount_column}")
    print(f"DEBUG: Income column: {income_column}")
    print(f"DEBUG: Description column: {description_column}")
    print(f"DEBUG: Source ID: {default_source_id}")
    
    conn = get_db_connection()
    
    # Read CSV
    stream = io.StringIO(csv_text)
    csv_reader = csv.DictReader(stream)
    
    imported_count = 0
    skipped_count = 0
    
    print(f"DEBUG: Starting to process rows...")
    row_num = 0
    for row in csv_reader:
        row_num += 1
        print(f"DEBUG: Row {row_num}: {dict(row)}")
        try:
            date_str = row.get(date_column, '').strip()
            expense_str = row.get(amount_column, '').strip()
            income_str = row.get(income_column, '').strip() if income_column else ''
            description = row.get(description_column, '').strip()
            
            if not date_str:
                continue
            
            # Skip if both expense and income are empty
            if not expense_str and not income_str:
                continue
            
            # Parse date
            import dateutil.parser
            date_obj = dateutil.parser.parse(date_str)
            date = date_obj.strftime('%Y-%m-%d')
            
            # Determine if this is income or expense
            is_income = False
            print(f"DEBUG: Row {row_num} - expense_str='{expense_str}', income_str='{income_str}'")
            if income_str and float(income_str.replace(',', '').replace('$', '') or '0') > 0:
                print(f"DEBUG: Row {row_num} - Classified as INCOME")
                # This row has income
                is_income = True
                amount = float(income_str.replace(',', '').replace('$', ''))
            elif expense_str:
                # This row has expense
                amount = float(expense_str.replace(',', '').replace('$', ''))
            else:
                continue
            
            amount = abs(amount)  # Make positive
            
            if is_income:
                # Check for duplicate income
                duplicate = conn.execute(
                    'SELECT id FROM income WHERE date = %s AND amount = %s',
                    (date, amount)
                ).fetchone()
                
                if duplicate:
                    skipped_count += 1
                    continue
                
                # Get source name from source_id
                source_row = conn.execute('SELECT name FROM sources WHERE id = %s', (default_source_id,)).fetchone()
                source_name = source_row['name'] if source_row else 'Unknown'
                
                # Insert as income (needs both source and source_id)
                conn.execute(
                    '''INSERT INTO income (date, description, amount, source, source_id)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (date, description, amount, source_name, default_source_id)
                )
                imported_count += 1
            else:
                # Check for duplicate expense
                duplicate = conn.execute(
                    'SELECT id FROM expenses WHERE date = %s AND amount = %s',
                    (date, amount)
                ).fetchone()
                
                if duplicate:
                    skipped_count += 1
                    continue
                
                # Insert expense
                conn.execute(
                    '''INSERT INTO expenses (date, description, amount, source_id)
                       VALUES (%s, %s, %s, %s)''',
                    (date, description, amount, default_source_id)
                )
                imported_count += 1
            
        except Exception as e:
            print(f"Error importing row: {e}")
            continue
    
    conn.commit()
    conn.close()
    
    # Clear session and temp file
    temp_id = session.pop('csv_temp_id', None)
    session.pop('csv_filename', None)
    
    if temp_id:
        temp_dir = os.path.join(os.path.expanduser('~/Documents/expense_tracker'), 'temp')
        temp_path = os.path.join(temp_dir, f'{temp_id}.csv')
        if os.path.exists(temp_path):
            os.remove(temp_path)
    
    print(f"DEBUG: Finished - Imported: {imported_count}, Skipped: {skipped_count}")
    
    return redirect(url_for('view_expenses', 
                          success=f'Imported {imported_count} expenses/income, skipped {skipped_count} duplicates'))




@app.route('/expenses/find-duplicates')
@login_required
def find_duplicates():
    """Find potential duplicate expenses"""
    from datetime import datetime, timedelta
    
    conn = get_db_connection()
    
    # Get all expenses
    all_expenses = conn.execute('''
        SELECT e.*, s.name as source_name, c.name as category_name, 
               sc.name as subcategory_name, v.name as vendor_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN categories c ON e.category_id = c.id
        LEFT JOIN subcategories sc ON e.subcategory_id = sc.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        ORDER BY e.date DESC, e.amount DESC
    ''').fetchall()
    
    # Find duplicates - TWO PASSES
    # Pass 1: Same amount + date + similar description
    # Pass 2: Same amount + date (regardless of description)
    
    duplicate_groups = []
    processed_ids = set()
    
    for i, expense in enumerate(all_expenses):
        if expense['id'] in processed_ids:
            continue
        
        # Look for duplicates of this expense
        exp_date = datetime.strptime(expense['date'], '%Y-%m-%d')
        date_minus_3 = (exp_date - timedelta(days=3)).strftime('%Y-%m-%d')
        date_plus_3 = (exp_date + timedelta(days=3)).strftime('%Y-%m-%d')
        
        duplicates = []
        
        for j, other in enumerate(all_expenses):
            if i == j or other['id'] in processed_ids:
                continue
            
            # Check if within date range and same amount
            if date_minus_3 <= other['date'] <= date_plus_3 and abs(expense['amount'] - other['amount']) < 0.01:
                # PASS 1: Check if descriptions are similar (first 15 chars)
                desc1 = expense['description'].lower()[:15]
                desc2 = other['description'].lower()[:15]
                
                if desc1 in desc2 or desc2 in desc1:
                    duplicates.append(dict(other))
                # PASS 2: If not similar description, still flag if EXACT same amount and vendor
                elif other['vendor_id'] and expense['vendor_id'] and other['vendor_id'] == expense['vendor_id']:
                    duplicates.append(dict(other))
                # PASS 3: If no description match and no vendor match, but same amount within 1 day (tighter window)
                elif abs((exp_date - datetime.strptime(other['date'], '%Y-%m-%d')).days) <= 1:
                    # Flag as potential duplicate (same amount within 24 hours)
                    duplicates.append(dict(other))
        
        # If we found duplicates, add as a group
        if duplicates:
            group = {
                'original': dict(expense),
                'duplicates': duplicates
            }
            duplicate_groups.append(group)
            
            # Mark all as processed
            processed_ids.add(expense['id'])
            for dup in duplicates:
                processed_ids.add(dup['id'])
    
    conn.close()
    
    return render_template('find_duplicates.html', 
                         duplicate_groups=duplicate_groups,
                         total_duplicates=sum(len(g['duplicates']) for g in duplicate_groups))




@app.route('/expenses/delete-duplicates', methods=['POST'])
@login_required
def delete_duplicates():
    """Delete selected duplicate expenses"""
    # Get selected IDs from form
    selected_ids = request.form.getlist('delete_ids')
    
    if not selected_ids:
        return redirect(url_for('find_duplicates'))
    
    conn = get_db_connection()
    
    deleted_count = 0
    for expense_id in selected_ids:
        conn.execute('DELETE FROM expenses WHERE id = %s', (expense_id,))
        deleted_count += 1
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('view_expenses', success=f'Deleted {deleted_count} duplicate expenses'))






@app.route('/api/add-category', methods=['POST'])
@login_required
def api_add_category():
    """Quick-add a category from edit page"""
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'success': False, 'error': 'Name required'})
    
    conn = get_db_connection()
    
    try:
        cursor = conn.execute('INSERT INTO categories (name) VALUES (%s)', (name,))
        category_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': category_id})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})




@app.route('/api/add-subcategory', methods=['POST'])
@login_required
def api_add_subcategory():
    """Quick-add a subcategory from edit page"""
    data = request.get_json()
    name = data.get('name', '').strip()
    category_id = data.get('category_id')
    
    if not name or not category_id:
        return jsonify({'success': False, 'error': 'Name and category required'})
    
    conn = get_db_connection()
    
    try:
        cursor = conn.execute('INSERT INTO subcategories (name, category_id) VALUES (%s, %s)', 
                            (name, category_id))
        subcategory_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': subcategory_id})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})




@app.route('/api/add-vendor', methods=['POST'])
@login_required
def api_add_vendor():
    """Quick-add a vendor from edit page"""
    data = request.get_json()
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'success': False, 'error': 'Name required'})
    
    conn = get_db_connection()
    
    try:
        cursor = conn.execute('INSERT INTO vendors (name) VALUES (%s)', (name,))
        vendor_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'id': vendor_id})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})




@app.route('/api/subcategories/<int:category_id>')
@login_required
def api_get_subcategories(category_id):
    """Get subcategories for a category"""
    conn = get_db_connection()
    subcategories = conn.execute(
        'SELECT id, name FROM subcategories WHERE category_id = %s ORDER BY name',
        (category_id,)
    ).fetchall()
    conn.close()
    
    return jsonify([{'id': s['id'], 'name': s['name']} for s in subcategories])






@app.route('/expense/archive/<int:expense_id>', methods=['POST'])
@login_required
def archive_expense(expense_id):
    """Archive an expense (hide from view but keep in reports)"""
    conn = get_db_connection()
    conn.execute('UPDATE expenses SET archived = 1 WHERE id = %s', (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_expenses'))




@app.route('/expense/unarchive/<int:expense_id>', methods=['POST'])
@login_required
def unarchive_expense(expense_id):
    """Unarchive an expense (make it visible again)"""
    conn = get_db_connection()
    conn.execute('UPDATE expenses SET archived = 0 WHERE id = %s', (expense_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('view_expenses', show_archived='true'))






@app.route('/expenses/bulk-archive', methods=['POST'])
@login_required
def bulk_archive_expenses():
    """Archive all expenses older than X months"""
    from datetime import datetime, timedelta
    
    months = request.form.get('months', type=int)
    if not months or months < 1:
        return redirect(url_for('view_expenses', error='Invalid month count'))
    
    # Calculate cutoff date (X months ago)
    today = datetime.now().date()
    cutoff_date = today - timedelta(days=months * 30)  # Approximate
    
    conn = get_db_connection()
    
    # Archive expenses older than cutoff date
    result = conn.execute(
        'UPDATE expenses SET archived = 1 WHERE date < %s AND archived = 0',
        (cutoff_date.strftime('%Y-%m-%d'),)
    )
    archived_count = result.rowcount
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('view_expenses', success=f'Archived {archived_count} expenses older than {months} months'))






@app.route('/expenses/bulk-unarchive', methods=['POST'])
@login_required
def bulk_unarchive_expenses():
    """Unarchive all archived expenses"""
    conn = get_db_connection()
    
    result = conn.execute('UPDATE expenses SET archived = 0 WHERE archived = 1')
    unarchived_count = result.rowcount
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('view_expenses', success=f'Unarchived {unarchived_count} expenses'))






@app.route('/budget/auto-generate')
@login_required
def auto_generate_budget():
    """Analyze spending patterns and suggest budget amounts"""
    from datetime import datetime, timedelta
    from collections import defaultdict
    
    conn = get_db_connection()
    
    # Get lookback period (default: last 12 months)
    lookback_months = request.args.get('months', 12, type=int)
    
    # Calculate date range
    today = datetime.now().date()
    start_date = (today - timedelta(days=lookback_months * 30)).replace(day=1)
    
    # Get all expenses in the period (including archived, excluding future)
    expenses = conn.execute('''
        SELECT category_id, subcategory_id, amount, date
        FROM expenses
        WHERE date >= %s AND date <= %s
        ORDER BY date
    ''', (start_date.isoformat(), today.isoformat())).fetchall()
    
    # Calculate months with ACTUAL data (not lookback period)
    if expenses:
        # Get the earliest and latest expense dates
        expense_dates = [datetime.strptime(exp['date'], '%Y-%m-%d').date() for exp in expenses]
        earliest_expense = min(expense_dates)
        latest_expense = max(expense_dates)
        
        # Calculate months between first and last expense
        months_analyzed = (latest_expense.year - earliest_expense.year) * 12 + (latest_expense.month - earliest_expense.month) + 1
    else:
        # No expenses found
        months_analyzed = 1
    
    # Aggregate by category and subcategory
    category_totals = defaultdict(float)
    subcategory_totals = defaultdict(lambda: defaultdict(float))
    
    for expense in expenses:
        category_totals[expense['category_id']] += expense['amount']
        if expense['subcategory_id']:
            subcategory_totals[expense['category_id']][expense['subcategory_id']] += expense['amount']
    
    # Calculate monthly averages
    suggestions = []
    
    for category_id, total in category_totals.items():
        monthly_avg = total / months_analyzed
        
        # Get category name
        category = conn.execute('SELECT name FROM categories WHERE id = %s', (category_id,)).fetchone()
        
        if category:
            suggestion = {
                'category_id': category_id,
                'category_name': category['name'],
                'total_spent': total,
                'monthly_avg': monthly_avg,
                'suggested_budget': round(monthly_avg * 1.1, 2),  # Add 10% buffer
                'subcategories': []
            }
            
            # Add subcategory breakdowns
            if category_id in subcategory_totals:
                for subcat_id, subcat_total in subcategory_totals[category_id].items():
                    subcat = conn.execute('SELECT name FROM subcategories WHERE id = %s', (subcat_id,)).fetchone()
                    if subcat:
                        subcat_avg = subcat_total / months_analyzed
                        suggestion['subcategories'].append({
                            'subcategory_id': subcat_id,
                            'subcategory_name': subcat['name'],
                            'total_spent': subcat_total,
                            'monthly_avg': subcat_avg,
                            'suggested_budget': round(subcat_avg * 1.1, 2)
                        })
            
            suggestions.append(suggestion)
    
    # Sort by total spent (highest first)
    suggestions.sort(key=lambda x: x['total_spent'], reverse=True)
    
    # Get current budgets for comparison
    current_budgets = conn.execute('''
        SELECT category_id, subcategory_id, monthly_amount
        FROM budgets
        WHERE is_active = 1
    ''').fetchall()
    
    current_budget_map = {}
    for budget in current_budgets:
        key = (budget['category_id'], budget['subcategory_id'])
        current_budget_map[key] = budget['monthly_amount']
    
    conn.close()
    
    return render_template('auto_budget.html',
                         suggestions=suggestions,
                         current_budgets=current_budget_map,
                         lookback_months=lookback_months,
                         months_analyzed=months_analyzed,
                         start_date=start_date,
                         end_date=today)




@app.route('/budget/apply-suggestions', methods=['POST'])
@login_required
def apply_budget_suggestions():
    """Apply suggested budgets (with optional adjustments)"""
    import json
    
    # Get selected suggestions from form
    suggestions_json = request.form.get('suggestions')
    if not suggestions_json:
        return redirect(url_for('budget'))
    
    suggestions = json.loads(suggestions_json)
    
    conn = get_db_connection()
    
    applied_count = 0
    
    for suggestion in suggestions:
        category_id = suggestion['category_id']
        amount = suggestion['amount']
        subcategory_id = suggestion.get('subcategory_id')
        
        # Check if budget exists
        existing = conn.execute(
            'SELECT id FROM budgets WHERE category_id = %s AND subcategory_id IS %s',
            (category_id, subcategory_id)
        ).fetchone()
        
        if existing:
            # Update existing
            conn.execute(
                'UPDATE budgets SET monthly_amount = %s, is_active = 1 WHERE id = %s',
                (amount, existing['id'])
            )
        else:
            # Create new
            conn.execute(
                'INSERT INTO budgets (category_id, subcategory_id, monthly_amount, is_active) VALUES (%s, %s, %s, 1)',
                (category_id, subcategory_id, amount)
            )
        
        applied_count += 1
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('budget', success=f'Applied {applied_count} budget suggestions'))






@app.route('/split-transaction/<int:expense_id>')
@login_required
def split_transaction(expense_id):
    """Split a transaction into multiple line items"""
    conn = get_db_connection()
    
    # Get the expense (could be parent or child of existing split)
    expense = conn.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    
    if not expense:
        return redirect(url_for('view_expenses', error='Expense not found'))
    
    # If this is a child, get the parent instead
    if expense['is_split'] == 2:
        parent_id = expense['parent_transaction_id']
        expense = conn.execute('SELECT * FROM expenses WHERE id = %s', (parent_id,)).fetchone()
        expense_id = parent_id
    
    # Get categories, subcategories, vendors, tax_rates
    categories = conn.execute('SELECT * FROM categories ORDER BY name').fetchall()
    subcategories = conn.execute('SELECT * FROM subcategories ORDER BY name').fetchall()
    vendors = conn.execute('SELECT * FROM vendors ORDER BY name').fetchall()
    tax_rates = conn.execute('SELECT * FROM tax_rates WHERE is_active = 1 ORDER BY display_order').fetchall()
    
    # Get existing splits if this is already split
    splits = []
    if expense['is_split'] == 1:
        splits = conn.execute(
            '''SELECT * FROM expenses 
               WHERE parent_transaction_id = %s 
               ORDER BY id''',
            (expense_id,)
        ).fetchall()
    
    # Get source name
    source = conn.execute('SELECT * FROM sources WHERE id = %s', (expense['source_id'],)).fetchone()
    
    conn.close()
    
    return render_template('split_transaction.html',
                         expense=expense,
                         source=source,
                         splits=splits,
                         categories=categories,
                         subcategories=subcategories,
                         vendors=vendors,
                         tax_rates=tax_rates)




@app.route('/save-split-transaction/<int:expense_id>', methods=['POST'])
@login_required
def save_split_transaction(expense_id):
    """Save split transaction with taxable checkboxes"""
    import json
    
    conn = get_db_connection()
    
    # Get original expense
    original = conn.execute('SELECT * FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    
    if not original:
        return redirect(url_for('view_expenses', error='Expense not found'))
    
    # Get splits and tax rate from form
    splits_json = request.form.get('splits_data')
    tax_rate = float(request.form.get('tax_rate', 0))
    
    print(f"DEBUG: Received splits_json: {splits_json}")
    print(f"DEBUG: Form data: {dict(request.form)}")
    
    if not splits_json:
        print("DEBUG: No splits_json - redirecting with error")
        return redirect(url_for('split_transaction', expense_id=expense_id, error='No split data received'))
    
    splits = json.loads(splits_json)
    
    # Validate total matches
    total_split = sum(float(split['amount']) for split in splits if split.get('amount'))
    print(f"DEBUG: total_split = {total_split}, original amount = {original['amount']}")
    print(f"DEBUG: Difference = {abs(total_split - original['amount'])}")
    if abs(total_split - original['amount']) > 0.01:
        print(f"DEBUG: VALIDATION FAILED - redirecting with error")
        return redirect(url_for('split_transaction', expense_id=expense_id, 
                              error=f'Split total ${total_split:.2f} must equal original ${original["amount"]:.2f}'))
    
    print(f"DEBUG: Validation passed! Proceeding to save...")
    
    # Delete existing splits if any
    conn.execute('DELETE FROM expenses WHERE parent_transaction_id = %s', (expense_id,))
    
    # Mark original as parent
    conn.execute('UPDATE expenses SET is_split = 1 WHERE id = %s', (expense_id,))
    
    # Create split transactions
    for split in splits:
        if not split.get('amount'):  # Skip empty rows
            continue
            
        # Get split details
        amount = float(split['amount'])
        tax_rate_id = split.get('tax_rate_id') or None
        tax_rate = float(split.get('tax_rate', 0))
        
        # Calculate tax for this split
        # amount is the subtotal, we calculate tax on top
        tax_amount = amount * (tax_rate / 100)
        subtotal = amount
        total_with_tax = subtotal + tax_amount
        
        # Insert split with tax calculation
        conn.execute(
            '''INSERT INTO expenses 
               (date, description, amount, subtotal, tax_rate_id, tax_amount, category_id, subcategory_id, vendor_id, source_id, notes, parent_transaction_id, is_split, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 2, CURRENT_TIMESTAMP)''',
            (original['date'],
             original['description'],
             total_with_tax,
             subtotal,
             tax_rate_id,
             tax_amount,
             split.get('category_id') or None,
             split.get('subcategory_id') or None,
             split.get('vendor_id') or None,
             original['source_id'],
             split.get('notes', ''),
             expense_id)
        )
    
    conn.commit()
    print(f"DEBUG: ✅ COMMITTED! Split into {len([s for s in splits if s.get('amount')])} parts")
    conn.close()
    
    return redirect(url_for('view_expenses', success=f'Transaction split into {len([s for s in splits if s.get("amount")])} parts'))




@app.route('/reset-split/<int:expense_id>', methods=['POST'])
@login_required
def reset_split(expense_id):
    """Reset a split transaction back to single transaction"""
    conn = get_db_connection()
    
    # Delete all child splits
    conn.execute('DELETE FROM expenses WHERE parent_transaction_id = %s', (expense_id,))
    
    # Mark parent as normal transaction
    conn.execute('UPDATE expenses SET is_split = 0 WHERE id = %s', (expense_id,))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('view_expenses', success='Split transaction reset to single transaction'))






@app.route('/admin/cleanup-orphaned-splits', methods=['POST'])
@login_required
def cleanup_orphaned_splits():
    """Find and delete orphaned child split transactions"""
    conn = get_db_connection()
    
    # Find all child splits whose parent doesn't exist
    orphans = conn.execute('''
        SELECT e.id, e.date, e.description, e.amount, e.parent_transaction_id
        FROM expenses e
        WHERE e.is_split = 2
          AND e.parent_transaction_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM expenses p WHERE p.id = e.parent_transaction_id
          )
        ORDER BY e.parent_transaction_id, e.id
    ''').fetchall()
    
    if orphans:
        # Delete orphaned transactions
        for orphan in orphans:
            conn.execute('DELETE FROM expenses WHERE id = %s', (orphan['id'],))
        
        conn.commit()
        count = len(orphans)
        message = f'Cleaned up {count} orphaned split transaction(s)'
    else:
        count = 0
        message = 'No orphaned split transactions found'
    
    conn.close()
    
    return redirect(url_for('admin', success=message))





@app.route('/view-receipt/<int:expense_id>')
@login_required
def view_receipt(expense_id):
    """View receipt file"""
    from flask import send_file
    conn = get_db_connection()
    expense = conn.execute('SELECT receipt_path FROM expenses WHERE id = %s', (expense_id,)).fetchone()
    conn.close()
    
    if expense and expense['receipt_path']:
        if os.path.exists(expense['receipt_path']):
            return send_file(expense['receipt_path'])
        else:
            return "Receipt file not found", 404
    else:
        return "No receipt attached", 404






@app.route('/pending-reimbursements')
@login_required
def pending_reimbursements():
    """Show pending reimbursement report"""
    conn = get_db_connection()
    
    # Get all pending reimbursements
    pending = conn.execute('''
        SELECT e.*, s.name as source_name, v.name as vendor_name, c.name as category_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.is_reimbursable = 1 AND e.is_reimbursed = 0
        ORDER BY e.date DESC
    ''').fetchall()
    
    # Calculate total
    total_pending = sum(row['amount'] for row in pending)
    
    conn.close()
    
    return render_template('pending_reimbursements.html',
                         pending=pending,
                         total_pending=total_pending)





@app.route('/pending-reimbursements/pdf')
@login_required
def pending_reimbursements_pdf():
    """Generate PDF of pending reimbursements"""
    from flask import make_response
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from io import BytesIO
    from datetime import datetime
    
    conn = get_db_connection()
    
    # Get all pending reimbursements
    pending = conn.execute('''
        SELECT e.*, s.name as source_name, v.name as vendor_name, c.name as category_name
        FROM expenses e
        LEFT JOIN sources s ON e.source_id = s.id
        LEFT JOIN vendors v ON e.vendor_id = v.id
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.is_reimbursable = 1 AND e.is_reimbursed = 0
        ORDER BY e.date DESC
    ''').fetchall()
    
    total_pending = sum(row['amount'] for row in pending)
    
    conn.close()
    
    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()
    
    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30,
    )
    elements.append(Paragraph("💰 Pending Reimbursements", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", styles['Normal']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Total box
    total_style = ParagraphStyle(
        'Total',
        parent=styles['Normal'],
        fontSize=16,
        textColor=colors.HexColor('#856404'),
        alignment=1,  # Center
    )
    elements.append(Paragraph(f"<b>Total Owed to You: ${total_pending:,.2f}</b>", total_style))
    elements.append(Spacer(1, 0.3*inch))
    
    if pending:
        # Table data
        data = [['Date', 'Description', 'Category', 'Amount']]
        
        for expense in pending:
            # Remove "To be paid back by " or "to be paid back by " from category
            category = expense['category_name'] or ''
            if ' by ' in category.lower():
                category = category.split(' by ', 1)[1] if len(category.split(' by ', 1)) > 1 else category
            
            data.append([
                expense['date'],
                expense['description'][:20],  # Shorter description
                category,
                f"${expense['amount']:,.2f}"
            ])
        
        # Create table
        table = Table(data, colWidths=[1*inch, 1.5*inch, 2.5*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f8f9fa')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#495057')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (-1, 0), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ]))
        
        elements.append(table)
    else:
        elements.append(Paragraph("No pending reimbursements! 🎉", styles['Normal']))
    
    doc.build(elements)
    
    pdf = buffer.getvalue()
    buffer.close()
    
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=pending_reimbursements_{datetime.now().strftime("%Y%m%d")}.pdf'
    
    return response





if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
