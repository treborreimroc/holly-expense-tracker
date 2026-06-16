import psycopg2
from urllib.parse import urlparse
import os

print("Adding placeholder entries for missing dates...")

database_url = os.environ.get('DATABASE_URL')
result = urlparse(database_url)
conn = psycopg2.connect(
    database=result.path[1:], user=result.username,
    password=result.password, host=result.hostname, port=result.port
)
cursor = conn.cursor()

placeholder_title = "Coming Soon"
placeholder_quote = "This entry is being written with care and intention. Something meaningful will be here soon."
placeholder_commentary = "This page is still being written. Check back soon, or if you are the author, use the Edit Entry button to add your content for this date."
placeholder_affirmation = "I am open to growth and new wisdom every single day of the year."

missing_dates = [
    (4,4),(4,25),(4,30),
    (5,26),(5,28),
    (6,15),(6,19),(6,20),
    (7,1),(7,6),(7,15),(7,16),(7,17),(7,18),(7,19),
    (7,21),(7,22),(7,23),(7,24),(7,25),(7,26),(7,27),(7,28),(7,29),(7,30),
    (8,6),(8,16),(8,17),(8,18),
    (9,16),(9,17),
    (10,17),
    (12,30),(12,31)
]

inserted = 0
for month, day in missing_dates:
    try:
        cursor.execute("""
            INSERT INTO inspiration_entries (month, day, title, quote, commentary, affirmation)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (month, day) DO NOTHING
        """, (month, day, placeholder_title, placeholder_quote, placeholder_commentary, placeholder_affirmation))
        inserted += 1
    except Exception as e:
        print(f"Error on {month}/{day}: {e}")

conn.commit()
cursor.close()
conn.close()
print(f"Done! Added {inserted} placeholder entries for {len(missing_dates)} missing dates.")
