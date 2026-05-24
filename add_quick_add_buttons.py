print("Adding quick-add buttons to Add/Edit Expense forms...")

# First, add the quick-add routes to app.py
with open('app.py', 'r') as f:
    app_content = f.read()

quick_add_routes = '''
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
'''

marker = "if __name__ == '__main__':"
pos = app_content.find(marker)
if pos > 0:
    app_content = app_content[:pos] + quick_add_routes + '\n' + app_content[pos:]

with open('app.py', 'w') as f:
    f.write(app_content)
print("✓ Added quick-add routes to app.py")

# Now update add_expense.html with + buttons
add_expense_with_buttons = '''{% extends "base.html" %}

{% block title %}Add Expense{% endblock %}

{% block content %}
<div class="container mt-4">
    <h2>Add New Expense</h2>
    
    <form method="POST" class="mt-4">
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="date" class="form-label">Date</label>
                <input type="date" class="form-control" id="date" name="date" 
                       value="{{ today }}" required>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="amount" class="form-label">Amount</label>
                <input type="number" step="0.01" class="form-control" id="amount" name="amount" 
                       placeholder="0.00" required autofocus>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="source_id" class="form-label">Source</label>
                <div class="input-group">
                    <select class="form-control" id="source_id" name="source_id" required>
                        <option value="">Select Source...</option>
                        {% for source in sources %}
                        <option value="{{ source.id }}">{{ source.name }}</option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddSource()">+</button>
                </div>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="category_id" class="form-label">Category</label>
                <div class="input-group">
                    <select class="form-control" id="category_id" name="category_id" required>
                        <option value="">Select Category...</option>
                        {% for category in categories %}
                        <option value="{{ category.id }}" data-category-id="{{ category.id }}">
                            {{ category.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddCategory()">+</button>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="subcategory_id" class="form-label">Subcategory (Optional)</label>
                <div class="input-group">
                    <select class="form-control" id="subcategory_id" name="subcategory_id">
                        <option value="">None</option>
                        {% for sub in subcategories %}
                        <option value="{{ sub.id }}" data-category="{{ sub.category_id }}" style="display:none;">
                            {{ sub.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddSubcategory()">+</button>
                </div>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="vendor_id" class="form-label">Vendor (Optional)</label>
                <div class="input-group">
                    <select class="form-control" id="vendor_id" name="vendor_id">
                        <option value="">None</option>
                        {% for vendor in vendors %}
                        <option value="{{ vendor.id }}">{{ vendor.name }}</option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddVendor()">+</button>
                </div>
            </div>
        </div>
        
        <div class="mb-3">
            <label for="description" class="form-label">Description</label>
            <input type="text" class="form-control" id="description" name="description" 
                   placeholder="Optional description">
        </div>
        
        <div class="mb-3">
            <label for="notes" class="form-label">Notes</label>
            <textarea class="form-control" id="notes" name="notes" rows="3" 
                      placeholder="Optional notes"></textarea>
        </div>
        
        <div class="d-grid gap-2">
            <button type="submit" class="btn btn-primary btn-lg">Add Expense</button>
            <a href="{{ url_for('view_expenses') }}" class="btn btn-secondary">Cancel</a>
        </div>
    </form>
</div>

<script>
// Filter subcategories based on selected category
document.getElementById('category_id').addEventListener('change', function() {
    const categoryId = this.value;
    const subcategorySelect = document.getElementById('subcategory_id');
    const options = subcategorySelect.querySelectorAll('option[data-category]');
    
    subcategorySelect.value = '';
    options.forEach(opt => opt.style.display = 'none');
    
    if (categoryId) {
        options.forEach(opt => {
            if (opt.getAttribute('data-category') === categoryId) {
                opt.style.display = 'block';
            }
        });
    }
});

// Quick Add functions
function quickAddSource() {
    const name = prompt('Enter new source name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_source") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('source_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddCategory() {
    const name = prompt('Enter new category name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_category") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('category_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddVendor() {
    const name = prompt('Enter new vendor name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_vendor") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('vendor_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddSubcategory() {
    const categoryId = document.getElementById('category_id').value;
    if (!categoryId) {
        alert('Please select a category first');
        return;
    }
    
    const name = prompt('Enter new subcategory name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_subcategory") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name) + '&category_id=' + categoryId
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('subcategory_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.setAttribute('data-category', categoryId);
                option.style.display = 'block';
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}
</script>
{% endblock %}
'''

with open('templates/add_expense.html', 'w') as f:
    f.write(add_expense_with_buttons)
print("✓ Updated add_expense.html with + buttons")

# Same for edit_expense.html (copy the same structure)
edit_expense_with_buttons = add_expense_with_buttons.replace(
    '{% block title %}Add Expense{% endblock %}',
    '{% block title %}Edit Expense{% endblock %}'
).replace(
    '<h2>Add New Expense</h2>',
    '<h2>Edit Expense</h2>'
).replace(
    '<button type="submit" class="btn btn-primary btn-lg">Add Expense</button>',
    '<button type="submit" class="btn btn-primary btn-lg">Save Changes</button>'
)

# Need to add the pre-filled values for edit
edit_expense_full = '''{% extends "base.html" %}

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
                <div class="input-group">
                    <select class="form-control" id="source_id" name="source_id" required>
                        <option value="">Select Source...</option>
                        {% for source in sources %}
                        <option value="{{ source.id }}" 
                                {% if source.id == expense.source_id %}selected{% endif %}>
                            {{ source.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddSource()">+</button>
                </div>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="category_id" class="form-label">Category</label>
                <div class="input-group">
                    <select class="form-control" id="category_id" name="category_id" required>
                        <option value="">Select Category...</option>
                        {% for category in categories %}
                        <option value="{{ category.id }}"
                                {% if category.id == expense.category_id %}selected{% endif %}>
                            {{ category.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddCategory()">+</button>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6 mb-3">
                <label for="subcategory_id" class="form-label">Subcategory (Optional)</label>
                <div class="input-group">
                    <select class="form-control" id="subcategory_id" name="subcategory_id">
                        <option value="">None</option>
                        {% for sub in subcategories %}
                        <option value="{{ sub.id }}" 
                                data-category="{{ sub.category_id }}"
                                {% if sub.id == expense.subcategory_id %}selected{% endif %}>
                            {{ sub.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddSubcategory()">+</button>
                </div>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="vendor_id" class="form-label">Vendor (Optional)</label>
                <div class="input-group">
                    <select class="form-control" id="vendor_id" name="vendor_id">
                        <option value="">None</option>
                        {% for vendor in vendors %}
                        <option value="{{ vendor.id }}"
                                {% if vendor.id == expense.vendor_id %}selected{% endif %}>
                            {{ vendor.name }}
                        </option>
                        {% endfor %}
                    </select>
                    <button type="button" class="btn btn-success" onclick="quickAddVendor()">+</button>
                </div>
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

<script>
function filterSubcategories() {
    const categoryId = document.getElementById('category_id').value;
    const subcategorySelect = document.getElementById('subcategory_id');
    const options = subcategorySelect.querySelectorAll('option[data-category]');
    
    options.forEach(opt => {
        if (!categoryId || opt.getAttribute('data-category') === categoryId) {
            opt.style.display = 'block';
        } else {
            opt.style.display = 'none';
        }
    });
}

filterSubcategories();
document.getElementById('category_id').addEventListener('change', filterSubcategories);

// Same quick-add functions as add_expense
function quickAddSource() {
    const name = prompt('Enter new source name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_source") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('source_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddCategory() {
    const name = prompt('Enter new category name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_category") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('category_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddVendor() {
    const name = prompt('Enter new vendor name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_vendor") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name)
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('vendor_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}

function quickAddSubcategory() {
    const categoryId = document.getElementById('category_id').value;
    if (!categoryId) {
        alert('Please select a category first');
        return;
    }
    
    const name = prompt('Enter new subcategory name:');
    if (name && name.trim()) {
        fetch('{{ url_for("quick_add_subcategory") }}', {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'name=' + encodeURIComponent(name) + '&category_id=' + categoryId
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                const select = document.getElementById('subcategory_id');
                const option = document.createElement('option');
                option.value = data.id;
                option.textContent = data.name;
                option.setAttribute('data-category', categoryId);
                option.style.display = 'block';
                option.selected = true;
                select.appendChild(option);
            }
        });
    }
}
</script>
{% endblock %}
'''

with open('templates/edit_expense.html', 'w') as f:
    f.write(edit_expense_full)
print("✓ Updated edit_expense.html with + buttons")

print("\n✅ Quick-add buttons ready!")
print("Upload: app.py, add_expense.html, edit_expense.html")
