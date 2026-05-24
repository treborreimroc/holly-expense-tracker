import psycopg2
from urllib.parse import urlparse
import os

print("Adding budget_subcategory table...")

database_url = os.environ.get('DATABASE_URL')
result = urlparse(database_url)
conn = psycopg2.connect(
    database=result.path[1:],
    user=result.username,
    password=result.password,
    host=result.hostname,
    port=result.port
)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS budget_subcategory (
        id SERIAL PRIMARY KEY,
        subcategory_id INTEGER REFERENCES subcategories(id),
        month VARCHAR(7) NOT NULL,
        amount DECIMAL(10,2) NOT NULL,
        UNIQUE(subcategory_id, month)
    )
""")

conn.commit()
cursor.close()
conn.close()
print("✅ budget_subcategory table created (or already existed)")
