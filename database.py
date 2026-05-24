import sqlite3
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'expense_tracker.db')

def get_db_connection():
    """Create a database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with all required tables"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Sources table (Royal Bank Visa, Checking, Cash, etc.)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Categories table (Food, Shelter, Bills, etc.)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#3498db',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Subcategories table (Groceries, Eating Out, Rent, etc.)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subcategories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories (id),
            UNIQUE(category_id, name)
        )
    ''')
    
    # Vendors table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            default_category_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (default_category_id) REFERENCES categories (id)
        )
    ''')
    
    # Expenses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            source_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            subcategory_id INTEGER,
            vendor_id INTEGER,
            amount REAL NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES sources (id),
            FOREIGN KEY (category_id) REFERENCES categories (id),
            FOREIGN KEY (subcategory_id) REFERENCES subcategories (id),
            FOREIGN KEY (vendor_id) REFERENCES vendors (id)
        )
    ''')
    
    # Debts table (credit cards, loans, etc.)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            source_id INTEGER,
            starting_balance REAL NOT NULL,
            current_balance REAL NOT NULL,
            interest_rate REAL NOT NULL,
            minimum_payment REAL NOT NULL,
            due_day INTEGER,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (source_id) REFERENCES sources (id)
        )
    ''')
    
    # Debt payments table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS debt_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            debt_id INTEGER NOT NULL,
            payment_date DATE NOT NULL,
            amount_paid REAL NOT NULL,
            interest_charged REAL NOT NULL DEFAULT 0,
            principal_paid REAL NOT NULL,
            balance_after REAL NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (debt_id) REFERENCES debts (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

def seed_initial_data():
    """Add some initial sample data to get started"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if data already exists
    cursor.execute("SELECT COUNT(*) as count FROM sources")
    if cursor.fetchone()['count'] > 0:
        print("Database already contains data. Skipping seed.")
        conn.close()
        return
    
    # Sample Sources
    sources = [
        ('Royal Bank Visa', 'Credit Card'),
        ('Royal Bank Checking', 'Bank Account'),
        ('Cash', 'Cash'),
        ('Debit Card', 'Debit Card')
    ]
    cursor.executemany('INSERT INTO sources (name, type) VALUES (?, ?)', sources)
    
    # Sample Categories with colors
    categories = [
        ('Food', '#e74c3c'),
        ('Shelter', '#3498db'),
        ('Bills', '#f39c12'),
        ('Transportation', '#9b59b6'),
        ('Entertainment', '#1abc9c'),
        ('Healthcare', '#e67e22'),
        ('Shopping', '#34495e'),
        ('Other', '#95a5a6')
    ]
    cursor.executemany('INSERT INTO categories (name, color) VALUES (?, ?)', categories)
    
    # Get category IDs for subcategories
    cursor.execute("SELECT id, name FROM categories")
    category_map = {row['name']: row['id'] for row in cursor.fetchall()}
    
    # Sample Subcategories
    subcategories = [
        # Food
        (category_map['Food'], 'Groceries'),
        (category_map['Food'], 'Eating Out'),
        (category_map['Food'], 'Coffee/Snacks'),
        (category_map['Food'], 'Takeout'),
        # Shelter
        (category_map['Shelter'], 'Rent'),
        (category_map['Shelter'], 'Mortgage'),
        (category_map['Shelter'], 'Property Tax'),
        (category_map['Shelter'], 'Home Insurance'),
        (category_map['Shelter'], 'Repairs/Maintenance'),
        # Bills
        (category_map['Bills'], 'Electricity'),
        (category_map['Bills'], 'Water'),
        (category_map['Bills'], 'Internet'),
        (category_map['Bills'], 'Phone'),
        (category_map['Bills'], 'Gas/Heat'),
        # Transportation
        (category_map['Transportation'], 'Gas'),
        (category_map['Transportation'], 'Car Payment'),
        (category_map['Transportation'], 'Car Insurance'),
        (category_map['Transportation'], 'Maintenance'),
        (category_map['Transportation'], 'Public Transit'),
        # Entertainment
        (category_map['Entertainment'], 'Movies/Streaming'),
        (category_map['Entertainment'], 'Hobbies'),
        (category_map['Entertainment'], 'Events'),
        (category_map['Entertainment'], 'Travel'),
        # Healthcare
        (category_map['Healthcare'], 'Insurance'),
        (category_map['Healthcare'], 'Prescriptions'),
        (category_map['Healthcare'], 'Doctor Visits'),
        # Shopping
        (category_map['Shopping'], 'Clothing'),
        (category_map['Shopping'], 'Electronics'),
        (category_map['Shopping'], 'Home Goods'),
        # Other
        (category_map['Other'], 'Miscellaneous')
    ]
    cursor.executemany('INSERT INTO subcategories (category_id, name) VALUES (?, ?)', subcategories)
    
    # Sample Vendors
    vendors = [
        ('Superstore', category_map['Food']),
        ('Sobeys', category_map['Food']),
        ('Tim Hortons', category_map['Food']),
        ('The Lefse House', category_map['Food']),
        ('SaskPower', category_map['Bills']),
        ('SaskTel', category_map['Bills']),
        ('Shell', category_map['Transportation']),
        ('Petro-Canada', category_map['Transportation'])
    ]
    cursor.executemany('INSERT INTO vendors (name, default_category_id) VALUES (?, ?)', vendors)
    
    conn.commit()
    conn.close()
    print("Sample data seeded successfully!")

if __name__ == '__main__':
    print("Initializing Expense Tracker Database...")
    init_database()
    seed_initial_data()
    print("\nDatabase setup complete!")
