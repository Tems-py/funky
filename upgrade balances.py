import datetime
import random
import datetime

from conf import config
import mysql.connector

db = mysql.connector.connect(
    host=config.database_login['host'],
    user=config.database_login['user'],
    password=config.database_login['password'],
    database=config.database_login['database']
)


amount = random.randrange(0, 50)
amount += 90
amount /= 100

cursor = db.cursor()
cursor.execute(f"UPDATE balance SET `virtual` = `virtual` * {amount}")
cursor.close()

timestamp = datetime.datetime.utcnow()

cursor = db.cursor()
cursor.execute("INSERT INTO profit (amount, date) VALUES (%s, %s)", (amount, timestamp))
db.commit()
