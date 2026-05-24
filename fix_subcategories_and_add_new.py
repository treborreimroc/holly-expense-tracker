print("Fixing subcategories and adding 'Add New' buttons...")

# First, let's update add_expense.html to have dynamic subcategory filtering
add_expense_update = '''{% extends "base.html" %}

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
                <select class="form-control" id="source_id" name="source_id" required>
                    <option value="">Select Source...</option>
                    {% for source in sources %}
                    <option value="{{ source.id }}">{{ source.name }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="col-md-6 mb-3">
                <label for="category_id" class="form-label">Category</label>
                <select class="form-control" id="category_id" name="category_id" required>
                    <option value="">Select Category...</option>
                    {% for category in categories %}
                    <option value="{{ category.id }}" data-category-id="{{ category.id }}">
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
                    <option value="{{ sub.id }}" data-category="{{ sub.category_id }}" style="display:none;">
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
                    <option value="{{ vendor.id }}">{{ vendor.name }}</option>
                    {% endfor %}
                </select>
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
    
    // Reset subcategory
    subcategorySelect.value = '';
    
    // Hide all subcategories
    options.forEach(opt => opt.style.display = 'none');
    
    // Show only subcategories for selected category
    if (categoryId) {
        options.forEach(opt => {
            if (opt.getAttribute('data-category') === categoryId) {
                opt.style.display = 'block';
            }
        });
    }
});
</script>
{% endblock %}
'''

with open('templates/add_expense.html', 'w') as f:
    f.write(add_expense_update)
print("✓ Updated add_expense.html with subcategory filtering")

# Do the same for edit_expense.html
edit_expense_update = '''{% extends "base.html" %}

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
                            data-category="{{ sub.category_id }}"
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

<script>
// Filter subcategories based on selected category
function filterSubcategories() {
    const categoryId = document.getElementById('category_id').value;
    const subcategorySelect = document.getElementById('subcategory_id');
    const options = subcategorySelect.querySelectorAll('option[data-category]');
    
    // Show/hide based on category
    options.forEach(opt => {
        if (!categoryId || opt.getAttribute('data-category') === categoryId) {
            opt.style.display = 'block';
        } else {
            opt.style.display = 'none';
        }
    });
}

// Run on page load
filterSubcategories();

// Run on category change
document.getElementById('category_id').addEventListener('change', filterSubcategories);
</script>
{% endblock %}
'''

with open('templates/edit_expense.html', 'w') as f:
    f.write(edit_expense_update)
print("✓ Updated edit_expense.html with subcategory filtering")

print("\n✅ Fixed subcategory filtering!")
print("Upload: add_expense.html, edit_expense.html")
print("\nNow test: Select 'Transportation' → You should see 'Gas' in subcategory dropdown")
