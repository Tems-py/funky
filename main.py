import datetime

import quart
from quart_cors import cors
from quart import request
import random
import hashlib
import secrets
from conf import config
import mysql.connector

db = mysql.connector.connect(
    host=config.database_login['host'],
    user=config.database_login['user'],
    password=config.database_login['password'],
    database=config.database_login['database']
)

AUTH_TOKEN = config.AUTH_TOKEN

# Create the app
app = quart.Quart(__name__)
app = cors(app, allow_origin="*")

salt = config.salt
cursor_update = db.cursor()


async def token_required(func):
    async def wrapper():
        token = (await request.form)['token']
        if token != AUTH_TOKEN:
            return quart.jsonify({'error': 'Invalid token'})
        func()

    return wrapper


async def params_required(func):
    async def wrapper(params):
        for param in params:
            if param not in (await request.form):
                return quart.jsonify({'error': 'Missing parameter: ' + param})
            if (await request.form)[param] == '':
                return quart.jsonify({'error': 'Missing parameter: ' + param})
        func()

    return wrapper


def create_tables():
    with open('create_tables.sql', 'r') as f:
        sql = f.read()
        cursor = db.cursor()
        cursor.execute(sql, multi=True)
        db.commit()
        cursor.close()


@app.route('/profit_history')
async def profit_history():
    cursor = db.cursor()
    cursor.execute("SELECT * FROM profit")
    result = cursor.fetchall()
    cursor.close()
    return quart.jsonify(result)


@app.route('/check_password/<code>/<password>')
async def check_password(code: int, password):
    random.seed(code)
    return code + ' ' + password + ' ' + random.random() % 100


@params_required(['token'])
@token_required
@app.route("/upgrade")
async def upgrade():
    amount = random.randrange(0, 50)
    amount += 90
    amount /= 100

    cursor = db.cursor()
    cursor.execute(f"UPDATE balance SET `virtual` = `virtual` * {amount}")
    cursor.close()
    db.commit()

    timestamp = datetime.datetime.utcnow()

    cursor = db.cursor()
    cursor.execute("INSERT INTO profit (amount, date) VALUES (%s, %s)", (amount, timestamp))
    db.commit()
    return quart.jsonify({'success': 'true'})


@params_required(['id', 'status', 'token'])
@token_required
@app.route('/change_payment_status', methods=['POST'])
async def change_payment_status():
    status = (await request.form)['status']
    payment_id = (await request.form)['id']
    cursor = db.cursor()
    cursor.execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))
    db.commit()
    return quart.jsonify({'status': 'ok'})


@app.route('/payments_requests')
async def payments_requests():
    # get payments from db
    cursor = db.cursor()
    cursor.execute("SELECT * FROM payments WHERE realised = 0")
    payments = cursor.fetchall()
    return quart.jsonify(payments)


@token_required
@params_required(['balance', 'username'])
@app.route("/virtual_update", methods=['POST'])
async def virtual_update():
    balance = (await request.form)['balance']
    username = (await request.form)['username']
    cursor = db.cursor()
    # check if user exists
    cursor.execute("SELECT * FROM balance WHERE username = %s", (username,))
    if cursor.fetchone() is None:
        # create user
        cursor.execute("INSERT INTO balance (username, virtual) VALUES (%s, %s)", (username, balance))
    else:
        cursor.execute("UPDATE balance SET virtual = %s WHERE username = %s", (balance, username))
    db.commit()
    return quart.jsonify({'status': 'ok'})


@token_required
@params_required(['balance', 'username'])
@app.route("/balance_update", methods=['POST'])
async def balance_update():
    balance = (await request.form)['balance']
    username = (await request.form)['username']
    # check if user exists
    cursor_update.execute("SELECT * FROM balance WHERE username = %s", (username,))
    if cursor_update.fetchone() is None:
        # create user
        cursor_update.execute("INSERT INTO balance (username, in_game) VALUES (%s, %s)", (username, balance))
    else:
        cursor_update.execute("UPDATE balance SET in_game = %s WHERE username = %s", (balance, username))
    if random.randint(1, 10) == 7:
        db.commit()
    return quart.jsonify({'status': 'ok'})


@app.route("/virtual_balance/<username>")
async def virtual_balance(username):
    # get virtual balance from db
    cursor = db.cursor()
    cursor.execute("SELECT `virtual` FROM balance WHERE username = %s", (username,))
    balance = cursor.fetchone()
    if balance is None:
        return quart.jsonify({'error': 'User not found'})
    return quart.jsonify(balance)


@app.route("/game_balance/<username>")
async def game_balance(username):
    # get game balance from db
    cursor = db.cursor()
    cursor.execute("SELECT `in_game` FROM balance WHERE username = %s", (username,))
    balance = cursor.fetchone()
    if balance is None:
        return quart.jsonify({'error': 'User not found'})
    return quart.jsonify(balance)


@params_required(['token', 'amount'])
@app.route('/create_payment', methods=['POST'])
async def payment():
    token = (await request.form)['token']
    amount = (await request.form)['amount']
    # Check if the token is valid
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT * FROM users WHERE token = %s", (token,))
    if cursor.rowcount == 0:
        return quart.jsonify({'error': 'Invalid token'})

    # get username from token
    cursor.execute("SELECT username FROM users WHERE token = %s", (token,))
    username = cursor.fetchone()[0]

    # check if user has enough money
    cursor.execute("SELECT virtual FROM balance WHERE username = %s", (username,))
    virtual = cursor.fetchone()[0]
    if virtual < amount:
        return quart.jsonify({'error': 'Not enough money'})

    # change balance
    cursor.execute("UPDATE balance SET `virtual` = `virtual` - %s WHERE username = %s", (amount, username))
    db.commit()

    # create payment
    cursor.execute("INSERT INTO payments (username, amount) VALUES (%s, %s)", (username, amount))
    db.commit()
    return quart.jsonify({'success': 'Payment created'})


@params_required(['username', 'password'])
@app.route("/register", methods=["POST"])
async def register():
    username = (await request.form)['username']
    password = (await request.form)['password']
    key = hashlib.sha256(salt + password.encode()).hexdigest()

    cursor = db.cursor()
    # check if user exists
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    if cursor.fetchone() is not None:
        return quart.jsonify({"error": "User already exists"})

    token = None

    # generate token
    token_registered = False
    while not token_registered:
        token = secrets.token_urlsafe()
        cursor.execute("SELECT * FROM users WHERE token = %s", (token,))
        if cursor.fetchone() is None:
            token_registered = True

    db_cursor = db.cursor()
    db_cursor.execute("INSERT INTO users (username, password, token) VALUES (%s, %s, %s)", (username, key, token))
    db.commit()

    return quart.jsonify({'username': username})


@params_required(['username', 'password'])
@app.route('/login/', methods=['POST'])
async def login():
    username = (await request.form)['username']
    password = (await request.form)['password']
    key = hashlib.sha256(salt + password.encode()).hexdigest()

    db_cursor = db.cursor()
    db_cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, key))
    if db_cursor.fetchone() is None:
        return quart.jsonify({"error": "Invalid username or password"})
    else:
        db_cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, key))
        user = db_cursor.fetchone()
        return quart.jsonify({'username': username, 'token': user[3]})


@app.route("/exptolvl/<num>")
async def exptolvl(num):
    i = 0
    num = int(num)
    while num >= 0:
        if i < 16:
            num -= (2 * i) + 7
        elif i < 31:
            num -= (5 * i) - 38
        else:
            num -= (9 * i) - 158
        i += 1
    return quart.jsonify({"level": i - 1})


@app.route('/')
async def index():
    return quart.redirect("https://github.com/Tems-py/funky")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.port)
    create_tables()
