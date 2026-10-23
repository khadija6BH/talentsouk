import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[2] / "database.db"
print("DB:", db, "| exists:", db.exists())

c = sqlite3.connect(db)

total, with_email = c.execute(
    "SELECT COUNT(*), SUM(COALESCE(email, '') != '') FROM companies"
).fetchone()
print(f"Companies: {total} | avec email: {with_email}")

print("\nIDs testés:")
for row in c.execute(
    "SELECT id, name, email FROM companies WHERE id IN (231, 76, 207)"
):
    print(" ", row)

print("\n5 sharikat b email (jarrab wa7da menhom f Postuler):")
for row in c.execute(
    "SELECT id, name, email FROM companies WHERE COALESCE(email, '') != '' LIMIT 5"
):
    print(" ", row)

c.close()
