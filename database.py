import psycopg2
import bcrypt
import os
from urllib.parse import urlparse

print("Creating PostgreSQL database schema...")

database_url = os.environ.get('DATABASE_URL')
if not database_url:
    print("ERROR: DATABASE_URL not set!")
    exit(1)

result = urlparse(database_url)

conn = psycopg2.connect(
    database=result.path[1:],
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)
cursor = conn.cursor()

# Drop existing tables
tables = ['debt_payments', 'debts', 'recurring_income', 'recurring_expenses', 
          'income_budget', 'budget', 'income', 'expenses', 'income_categories',
          'tax_rates', 'vendors', 'subcategories', 'categories', 'sources', 'users']

for table in tables:
    cursor.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

# Create users table
cursor.execute("""
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
""")

# Create sources table
cursor.execute("""
    CREATE TABLE sources (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        type VARCHAR(100)
    )
""")

# Create categories table
cursor.execute("""
    CREATE TABLE categories (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        color VARCHAR(20) DEFAULT '#6c757d'
    )
""")

# Create subcategories table  
cursor.execute("""
    CREATE TABLE subcategories (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        category_id INTEGER REFERENCES categories(id)
    )
""")

# Create vendors table
cursor.execute("""
    CREATE TABLE vendors (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE
    )
""")

# Create tax_rates table
cursor.execute("""
    CREATE TABLE tax_rates (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        rate DECIMAL(5,2) NOT NULL,
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
""")

# Create expenses table
cursor.execute("""
    CREATE TABLE expenses (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        source_id INTEGER REFERENCES sources(id),
        description TEXT,
        category_id INTEGER REFERENCES categories(id),
        subcategory_id INTEGER REFERENCES subcategories(id),
        vendor_id INTEGER REFERENCES vendors(id),
        amount DECIMAL(10,2) NOT NULL,
        notes TEXT,
        receipt_path VARCHAR(500),
        imported_from_mobile INTEGER DEFAULT 0,
        is_split INTEGER DEFAULT 0,
        parent_transaction_id INTEGER,
        taxable INTEGER DEFAULT 0,
        tax_rate_id INTEGER REFERENCES tax_rates(id),
        subtotal DECIMAL(10,2),
        tax_amount DECIMAL(10,2),
        archived INTEGER DEFAULT 0,
        recurring_id INTEGER,
        is_reimbursable INTEGER DEFAULT 0,
        is_reimbursed INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Create income_categories table
cursor.execute("""
    CREATE TABLE income_categories (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        color VARCHAR(20) DEFAULT '#28a745'
    )
""")

# Create income table
cursor.execute("""
    CREATE TABLE income (
        id SERIAL PRIMARY KEY,
        date DATE NOT NULL,
        source_id INTEGER REFERENCES sources(id),
        description TEXT,
        category_id INTEGER REFERENCES income_categories(id),
        amount DECIMAL(10,2) NOT NULL,
        notes TEXT,
        archived INTEGER DEFAULT 0,
        recurring_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Create budget table
cursor.execute("""
    CREATE TABLE budget (
        id SERIAL PRIMARY KEY,
        category_id INTEGER REFERENCES categories(id),
        month VARCHAR(7) NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        UNIQUE(category_id, month)
    )
""")

# Create income_budget table
cursor.execute("""
    CREATE TABLE income_budget (
        id SERIAL PRIMARY KEY,
        category_id INTEGER REFERENCES income_categories(id),
        month VARCHAR(7) NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        UNIQUE(category_id, month)
    )
""")

# Create recurring_expenses table
cursor.execute("""
    CREATE TABLE recurring_expenses (
        id SERIAL PRIMARY KEY,
        source_id INTEGER REFERENCES sources(id),
        description TEXT,
        category_id INTEGER REFERENCES categories(id),
        subcategory_id INTEGER REFERENCES subcategories(id),
        vendor_id INTEGER REFERENCES vendors(id),
        amount DECIMAL(10,2) NOT NULL,
        notes TEXT,
        frequency VARCHAR(20) NOT NULL,
        day_of_week INTEGER,
        day_of_month INTEGER,
        start_date DATE NOT NULL,
        end_date DATE,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Create recurring_income table
cursor.execute("""
    CREATE TABLE recurring_income (
        id SERIAL PRIMARY KEY,
        source_id INTEGER REFERENCES sources(id),
        description TEXT,
        category_id INTEGER REFERENCES income_categories(id),
        amount DECIMAL(10,2) NOT NULL,
        notes TEXT,
        frequency VARCHAR(20) NOT NULL,
        day_of_week INTEGER,
        day_of_month INTEGER,
        start_date DATE NOT NULL,
        end_date DATE,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Create debts table
cursor.execute("""
    CREATE TABLE debts (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        initial_balance DECIMAL(10,2) NOT NULL,
        current_balance DECIMAL(10,2) NOT NULL,
        interest_rate DECIMAL(5,2) DEFAULT 0,
        minimum_payment DECIMAL(10,2) DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")

# Create debt_payments table
cursor.execute("""
    CREATE TABLE debt_payments (
        id SERIAL PRIMARY KEY,
        debt_id INTEGER REFERENCES debts(id),
        date DATE NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        notes TEXT
    )
""")

# Insert default admin user
hashed = bcrypt.hashpw(b'admin123', bcrypt.gensalt())
cursor.execute('INSERT INTO users (username, password) VALUES (%s, %s)', 
               ('admin', hashed.decode('utf-8')))

# Insert default sources
cursor.execute("INSERT INTO sources (name, type) VALUES (%s, %s)", ('Cash', 'Cash'))
cursor.execute("INSERT INTO sources (name, type) VALUES (%s, %s)", ('Debit Card', 'Bank Account'))
cursor.execute("INSERT INTO sources (name, type) VALUES (%s, %s)", ('Credit Card', 'Credit Card'))

# Insert default categories
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Food', '#ff6b6b'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Shelter', '#4ecdc4'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Bills', '#95e1d3'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Transportation', '#feca57'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Entertainment', '#ff9ff3'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Healthcare', '#48dbfb'))
cursor.execute("INSERT INTO categories (name, color) VALUES (%s, %s)", ('Shopping', '#1dd1a1'))

# Insert default income categories
cursor.execute("INSERT INTO income_categories (name, color) VALUES (%s, %s)", 
               ('Wages/Salary', '#28a745'))
cursor.execute("INSERT INTO income_categories (name, color) VALUES (%s, %s)", 
               ('Business Income', '#20c997'))
cursor.execute("INSERT INTO income_categories (name, color) VALUES (%s, %s)", 
               ('Investment Income', '#17a2b8'))

# Insert default tax rates
cursor.execute("INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, %s, %s)", 
               ('No Tax', 0, 0, 1))
cursor.execute("INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, %s, %s)", 
               ('GST (5%)', 5, 1, 1))
cursor.execute("INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, %s, %s)", 
               ('PST (7%)', 7, 2, 1))
cursor.execute("INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, %s, %s)", 
               ('HST (13%)', 13, 3, 1))

conn.commit()
conn.close()

print("✅ PostgreSQL database created successfully!")
print("Login with password: admin123")
