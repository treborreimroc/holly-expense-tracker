print("Adding Manage Categories/Sources/Vendors...")

with open('app.py', 'r') as f:
    app_content = f.read()

# Add all the manage routes
manage_routes = '''
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
'''

# Insert before if __name__
marker = "if __name__ == '__main__':"
pos = app_content.find(marker)
if pos > 0:
    app_content = app_content[:pos] + manage_routes + '\n' + app_content[pos:]
    print("✓ Added manage routes")

with open('app.py', 'w') as f:
    f.write(app_content)

# Update manage.html to add links
manage_template = '''{% extends "base.html" %}

{% block title %}Admin{% endblock %}

{% block content %}
<div class="container mt-4">
    <h2>Admin Dashboard</h2>
    
    <div class="row mt-4">
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Sources</h5>
                    <p class="card-text display-4">{{ stats.sources }}</p>
                    <a href="{{ url_for('manage_sources') }}" class="btn btn-primary">Manage</a>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Categories</h5>
                    <p class="card-text display-4">{{ stats.categories }}</p>
                    <a href="{{ url_for('manage_categories') }}" class="btn btn-primary">Manage</a>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Vendors</h5>
                    <p class="card-text display-4">{{ stats.vendors }}</p>
                    <a href="{{ url_for('manage_vendors') }}" class="btn btn-primary">Manage</a>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Expenses</h5>
                    <p class="card-text display-4">{{ stats.expenses }}</p>
                </div>
            </div>
        </div>
    </div>
    
    <div class="mt-4">
        <a href="{{ url_for('manage_subcategories') }}" class="btn btn-secondary">Manage Subcategories</a>
    </div>
</div>
{% endblock %}
'''

with open('templates/manage.html', 'w') as f:
    f.write(manage_template)
print("✓ Updated manage.html")

# Create manage templates (I'll create a simple reusable one for each)
sources_template = '''{% extends "base.html" %}
{% block title %}Manage Sources{% endblock %}
{% block content %}
<div class="container mt-4">
    <h2>Manage Sources</h2>
    
    <div class="card mt-4">
        <div class="card-header">Add New Source</div>
        <div class="card-body">
            <form method="POST" action="{{ url_for('add_source') }}">
                <div class="row">
                    <div class="col-md-6">
                        <input type="text" name="name" class="form-control" placeholder="Source Name" required>
                    </div>
                    <div class="col-md-4">
                        <select name="type" class="form-control">
                            <option value="">Type (optional)</option>
                            <option value="Bank Account">Bank Account</option>
                            <option value="Credit Card">Credit Card</option>
                            <option value="Cash">Cash</option>
                        </select>
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-success w-100">Add</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    
    <table class="table table-striped mt-4">
        <thead>
            <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for source in sources %}
            <tr>
                <td>{{ source.name }}</td>
                <td>{{ source.type or '-' }}</td>
                <td>
                    <form method="POST" action="{{ url_for('delete_source', source_id=source.id) }}" 
                          style="display:inline;"
                          onsubmit="return confirm('Delete this source?')">
                        <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <a href="{{ url_for('manage') }}" class="btn btn-secondary">Back to Admin</a>
</div>
{% endblock %}
'''

categories_template = '''{% extends "base.html" %}
{% block title %}Manage Categories{% endblock %}
{% block content %}
<div class="container mt-4">
    <h2>Manage Categories</h2>
    
    <div class="card mt-4">
        <div class="card-header">Add New Category</div>
        <div class="card-body">
            <form method="POST" action="{{ url_for('add_category') }}">
                <div class="row">
                    <div class="col-md-6">
                        <input type="text" name="name" class="form-control" placeholder="Category Name" required>
                    </div>
                    <div class="col-md-4">
                        <input type="color" name="color" class="form-control" value="#6c757d">
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-success w-100">Add</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    
    <table class="table table-striped mt-4">
        <thead>
            <tr>
                <th>Name</th>
                <th>Color</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for category in categories %}
            <tr>
                <td>{{ category.name }}</td>
                <td><span class="badge" style="background-color: {{ category.color }}">{{ category.color }}</span></td>
                <td>
                    <form method="POST" action="{{ url_for('delete_category', category_id=category.id) }}" 
                          style="display:inline;"
                          onsubmit="return confirm('Delete this category?')">
                        <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <a href="{{ url_for('manage') }}" class="btn btn-secondary">Back to Admin</a>
</div>
{% endblock %}
'''

vendors_template = '''{% extends "base.html" %}
{% block title %}Manage Vendors{% endblock %}
{% block content %}
<div class="container mt-4">
    <h2>Manage Vendors</h2>
    
    <div class="card mt-4">
        <div class="card-header">Add New Vendor</div>
        <div class="card-body">
            <form method="POST" action="{{ url_for('add_vendor') }}">
                <div class="row">
                    <div class="col-md-10">
                        <input type="text" name="name" class="form-control" placeholder="Vendor Name" required>
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-success w-100">Add</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    
    <table class="table table-striped mt-4">
        <thead>
            <tr>
                <th>Name</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for vendor in vendors %}
            <tr>
                <td>{{ vendor.name }}</td>
                <td>
                    <form method="POST" action="{{ url_for('delete_vendor', vendor_id=vendor.id) }}" 
                          style="display:inline;"
                          onsubmit="return confirm('Delete this vendor?')">
                        <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <a href="{{ url_for('manage') }}" class="btn btn-secondary">Back to Admin</a>
</div>
{% endblock %}
'''

subcategories_template = '''{% extends "base.html" %}
{% block title %}Manage Subcategories{% endblock %}
{% block content %}
<div class="container mt-4">
    <h2>Manage Subcategories</h2>
    
    <div class="card mt-4">
        <div class="card-header">Add New Subcategory</div>
        <div class="card-body">
            <form method="POST" action="{{ url_for('add_subcategory') }}">
                <div class="row">
                    <div class="col-md-6">
                        <input type="text" name="name" class="form-control" placeholder="Subcategory Name" required>
                    </div>
                    <div class="col-md-4">
                        <select name="category_id" class="form-control" required>
                            <option value="">Select Category</option>
                            {% for category in categories %}
                            <option value="{{ category.id }}">{{ category.name }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-success w-100">Add</button>
                    </div>
                </div>
            </form>
        </div>
    </div>
    
    <table class="table table-striped mt-4">
        <thead>
            <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Actions</th>
            </tr>
        </thead>
        <tbody>
            {% for sub in subcategories %}
            <tr>
                <td>{{ sub.name }}</td>
                <td>{{ sub.category_name }}</td>
                <td>
                    <form method="POST" action="{{ url_for('delete_subcategory', subcategory_id=sub.id) }}" 
                          style="display:inline;"
                          onsubmit="return confirm('Delete this subcategory?')">
                        <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    
    <a href="{{ url_for('manage') }}" class="btn btn-secondary">Back to Admin</a>
</div>
{% endblock %}
'''

with open('templates/manage_sources.html', 'w') as f:
    f.write(sources_template)
print("✓ Created manage_sources.html")

with open('templates/manage_categories.html', 'w') as f:
    f.write(categories_template)
print("✓ Created manage_categories.html")

with open('templates/manage_vendors.html', 'w') as f:
    f.write(vendors_template)
print("✓ Created manage_vendors.html")

with open('templates/manage_subcategories.html', 'w') as f:
    f.write(subcategories_template)
print("✓ Created manage_subcategories.html")

print("\n✅ Management features ready!")
print("Upload: app.py, manage.html, manage_sources.html, manage_categories.html,")
print("        manage_vendors.html, manage_subcategories.html")
