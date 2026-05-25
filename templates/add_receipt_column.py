import psycopg2
from urllib.parse import urlparse
import os

print("Adding receipt column to expenses table...")

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

# Add receipt columns if they don't exist
cursor.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='expenses' AND column_name='receipt_data'
        ) THEN
            ALTER TABLE expenses ADD COLUMN receipt_data BYTEA;
        END IF;

        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name='expenses' AND column_name='receipt_mime_type'
        ) THEN
            ALTER TABLE expenses ADD COLUMN receipt_mime_type VARCHAR(50);
        END IF;
    END$$;
""")

conn.commit()
cursor.close()
conn.close()
print("✅ Receipt columns added successfully!")
