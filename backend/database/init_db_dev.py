import mysql.connector

dbName = "agents"
password = "deepa2497"

# Connect to MySQL
connection = mysql.connector.connect(
    user='root',
    password=password,
    unix_socket='/tmp/mysql.sock',
    database=dbName,
)

# Create a cursor
cur = connection.cursor()

# Read and execute schema.sql
with open('schema.sql', 'r') as file:
    schema_sql = file.read()

# Execute SQL commands
for result in cur.execute(schema_sql, multi=True):
    print(f"Executed: {result}")

# Close the connection
connection.close()
