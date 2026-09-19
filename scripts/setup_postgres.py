import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

conn = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/postgres')
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()

cur.execute("SELECT 1 FROM pg_roles WHERE rolname='airfare_user'")
if not cur.fetchone():
    cur.execute("CREATE USER airfare_user WITH PASSWORD 'apix_dev_password_2024' CREATEDB")
    print("Created user airfare_user")
else:
    cur.execute("ALTER USER airfare_user WITH PASSWORD 'apix_dev_password_2024' CREATEDB")
    print("Updated airfare_user")

cur.execute("SELECT 1 FROM pg_database WHERE datname='airfare_db'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE airfare_db OWNER airfare_user")
    print("Created database airfare_db")
else:
    print("Database airfare_db exists")

cur.execute("SELECT 1 FROM pg_database WHERE datname='airfare_test_db'")
if not cur.fetchone():
    cur.execute("CREATE DATABASE airfare_test_db OWNER airfare_user")
    print("Created database airfare_test_db")
else:
    print("Database airfare_test_db exists")

cur.close()
conn.close()
print("PostgreSQL configuration completed!")
