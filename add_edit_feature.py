print("Adding Edit Expenses feature...")

with open('app.py', 'r') as f:
    app_content = f.read()

# Add the edit route before the if __name__ block
edit_route = '''
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
'''

# Insert before if __name__
marker = "if __name__ == '__main__':"
pos = app_content.find(marker)
if pos > 0:
    app_content = app_content[:pos] + edit_route + '\n' + app_content[pos:]
    print("✓ Added edit_expense route")

with open('app.py', 'w') as f:
    f.write(app_content)

# Create edit template
edit_template = '''{% extends "base.html" %}

{% block title %}Edit Expense{% endblock %}

{% block content %}
<div class="container mt-4">
    <h2>Edit Expense</h2>
    
    <form method="POST" class="mt-4">
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="date" class="form-label">Date</label>
                <input type="date" class="form-control" id="date" name="date" 
                       value="{{ expense.date }}" required>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="amount" class="form-label">Amount</label>
                <input type="number" step="0.01" class="form-control" id="amount" name="amount" 
                       value="{{ expense.amount }}" required>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="source_id" class="form-label">Source</label>
                <select class="form-control" id="source_id" name="source_id" required>
                    <option value="">Select Source...</option>
                    {% for source in sources %}
                    <option value="{{ source.id }}" 
                            {% if source.id == expense.source_id %}selected{% endif %}>
                        {{ source.name }}
                    </option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="category_id" class="form-label">Category</label>
                <select class="form-control" id="category_id" name="category_id" required>
                    <option value="">Select Category...</option>
                    {% for category in categories %}
                    <option value="{{ category.id }}"
                            {% if category.id == expense.category_id %}selected{% endif %}>
                        {{ category.name }}
                    </option>
                    {% endfor %}
                </select>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="subcategory_id" class="form-label">Subcategory (Optional)</label>
                <select class="form-control" id="subcategory_id" name="subcategory_id">
                    <option value="">None</option>
                    {% for sub in subcategories %}
                    <option value="{{ sub.id }}"
                            {% if sub.id == expense.subcategory_id %}selected{% endif %}>
                        {{ sub.name }}
                    </option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="vendor_id" class="form-label">Vendor (Optional)</label>
                <select class="form-control" id="vendor_id" name="vendor_id">
                    <option value="">None</option>
                    {% for vendor in vendors %}
                    <option value="{{ vendor.id }}"
                            {% if vendor.id == expense.vendor_id %}selected{% endif %}>
                        {{ vendor.name }}
                    </option>
                    {% endfor %}
                </select>
            </div>
        </div>
        
        <div class="mb-3">
            <label for="description" class="form-label">Description</label>
            <input type="text" class="form-control" id="description" name="description" 
                   value="{{ expense.description or '' }}">
        </div>
        
        <div class="mb-3">
            <label for="notes" class="form-label">Notes</label>
            <textarea class="form-control" id="notes" name="notes" rows="3">{{ expense.notes or '' }}</textarea>
        </div>
        
        <div class="d-grid gap-2">
            <button type="submit" class="btn btn-primary btn-lg">Save Changes</button>
            <a href="{{ url_for('view_expenses') }}" class="btn btn-secondary">Cancel</a>
        </div>
    </form>
</div>
{% endblock %}
'''

with open('templates/edit_expense.html', 'w') as f:
    f.write(edit_template)
print("✓ Created edit_expense.html")

# Update view_expenses.html to add Edit button
with open('templates/view_expenses.html', 'r') as f:
    view_content = f.read()

# Add Edit button before Delete
old_actions = '''                <td>
                    <form method="POST" action="{{ url_for('delete_expense', expense_id=expense.id) }}"'''

new_actions = '''                <td>
                    <a href="{{ url_for('edit_expense', expense_id=expense.id) }}" 
                       class="btn btn-primary btn-sm">Edit</a>
                    <form method="POST" action="{{ url_for('delete_expense', expense_id=expense.id) }}"'''

view_content = view_content.replace(old_actions, new_actions)

with open('templates/view_expenses.html', 'w') as f:
    f.write(view_content)
print("✓ Updated view_expenses.html with Edit button")

print("\n✅ Edit feature ready!")
print("Upload: app.py, edit_expense.html, view_expenses.html")
