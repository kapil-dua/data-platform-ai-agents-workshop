import sqlite3

conn = sqlite3.connect(".data/agent_state.db")
cur = conn.cursor()

# List tables
print(cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;").fetchall())

# Inspect the checkpoint table
for row in cur.execute("SELECT * FROM sqlite_master WHERE type='table' LIMIT 10"):
    print(row)

# If your graph uses checkpoint tables, you can query them
for row in cur.execute("SELECT * FROM incidents LIMIT 5"):
    print(row)