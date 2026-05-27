import psycopg2
from urllib.parse import urlparse
import os

print("Setting up tax rates...")

database_url = os.environ.get('DATABASE_URL')
result = urlparse(database_url)
conn = psycopg2.connect(
    database=result.path[1:],
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)
conn.autocommit = True
cursor = conn.cursor()

# Add columns to expenses if they don't exist
for col, coltype in [('subtotal', 'DECIMAL(10,2)'), ('tax_amount', 'DECIMAL(10,2)'), ('tax_rate_id', 'INTEGER')]:
    try:
        cursor.execute(f'ALTER TABLE expenses ADD COLUMN {col} {coltype}')
        print(f"✅ Added {col} column")
    except psycopg2.errors.DuplicateColumn:
        print(f"✓ {col} already exists")

# Create tax_rates table if not exists
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tax_rates (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        rate DECIMAL(5,2) NOT NULL,
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
""")
print("✅ tax_rates table ready")

# Clear and re-seed default tax rates
cursor.execute("SELECT COUNT(*) FROM tax_rates")
count = cursor.fetchone()[0]

if count == 0:
    rates = [
        ('No Tax (0%)',                    0.00,  0),
        ('GST (5%)',                        5.00,  1),
        ('PST - Saskatchewan (6%)',         6.00,  2),
        ('GST + PST - Saskatchewan (11%)', 11.00,  3),
        ('GST + PST - Manitoba (12%)',     12.00,  4),
        ('HST - Ontario (13%)',            13.00,  5),
        ('HST - Maritimes (15%)',          15.00,  6),
    ]
    for name, rate, order in rates:
        cursor.execute(
            'INSERT INTO tax_rates (name, rate, display_order, is_active) VALUES (%s, %s, %s, 1)',
            (name, rate, order)
        )
    print(f"✅ Seeded {len(rates)} default tax rates")
else:
    print(f"✓ Tax rates already exist ({count} records) — skipping seed")

cursor.close()
conn.close()
print("✅ Tax migration complete!")
