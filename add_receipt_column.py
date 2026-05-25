import psycopg2
from urllib.parse import urlparse
import os

print("Adding receipt columns to expenses table...")

database_url = os.environ.get('DATABASE_URL')
result = urlparse(database_url)
conn = psycopg2.connect(
    database=result.path[1:],
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)
conn.autocommit = True  # Each statement is its own transaction
cursor = conn.cursor()

# Add receipt_data column if not exists
try:
    cursor.execute('ALTER TABLE expenses ADD COLUMN receipt_data BYTEA')
    print("✅ Added receipt_data column")
except psycopg2.errors.DuplicateColumn:
    print("✓ receipt_data column already exists")

# Add receipt_mime_type column if not exists
try:
    cursor.execute("ALTER TABLE expenses ADD COLUMN receipt_mime_type VARCHAR(50)")
    print("✅ Added receipt_mime_type column")
except psycopg2.errors.DuplicateColumn:
    print("✓ receipt_mime_type column already exists")

cursor.close()
conn.close()
print("✅ Migration complete!")
