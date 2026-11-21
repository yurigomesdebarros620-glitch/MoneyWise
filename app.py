"""MoneyWise: acesso multiusuário com login e persistência em SQLite."""
import math
import json
import os
import sqlite3
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from local_ai_service import LocalAIError, generate_reply, validate_chat, stream_reply, local_status
from financial_context import financial_context
from financial_answers import answer_from_data

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "moneywise-chave-secreta-2026-altere-no-servidor")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=30)

app.config["DATABASE"] = os.environ.get(
    "MONEYWISE_DB", str(Path(__file__).with_name("moneywise.db"))
)

FIXED_USERS = [
    (1, 'Yuri', 'Meu Espaço', '0720'),
    (2, 'escola', 'Apresentação Escolar', '1234'),
]

CATEGORIES = [
    "Alimentação",
    "Moradia",
    "Transporte",
    "Lazer",
    "Educação",
    "Saúde",
    "Salário",
    "Freelance",
    "Outros",
]


class DatabaseConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def db():
    conn = sqlite3.connect(app.config["DATABASE"], factory=DatabaseConnection)
    conn.row_factory = sqlite3.Row
    return conn


def money(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > 100000000:
            raise ValueError("Valor fora do intervalo permitido.")
        return int((n * 100).quantize(Decimal("1")))
    except (InvalidOperation, TypeError):
        raise ValueError("Informe um valor válido.")


def initialize():
    with db() as c:
        c.executescript(
            """CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                plan TEXT NOT NULL DEFAULT 'premium'
            );
            CREATE TABLE IF NOT EXISTS transactions(
                id INTEGER PRIMARY KEY,
                description TEXT NOT NULL,
                amount INTEGER NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS goals(
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                target INTEGER NOT NULL,
                saved INTEGER NOT NULL,
                deadline TEXT NOT NULL,
                user_id INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY);"""
        )
        for table in ("transactions", "goals"):
            cols = [row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()]
            if "user_id" not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

        c.executemany("INSERT OR IGNORE INTO categories VALUES(?)", [(x,) for x in CATEGORIES])
        c.execute("INSERT OR IGNORE INTO settings VALUES ('plan','premium')")

        for uid, uname, dname, raw_pwd in FIXED_USERS:
            existing = c.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
            if not existing:
                c.execute(
                    "INSERT INTO users(id, username, display_name, password_hash, plan) VALUES(?,?,?,?,?)",
                    (uid, uname.lower(), dname, generate_password_hash(raw_pwd), "premium"),
                )


def current_user_id():
    return int(session["user_id"])


def plan():
    with db() as c:
        row = c.execute("SELECT plan FROM users WHERE id=?", (current_user_id(),)).fetchone()
        return row[0] if row else "premium"


def require(level):
    if ["free", "plus", "premium"].index(plan()) < ["free", "plus", "premium"].index(level):
        return (
            jsonify(
                error="Recurso do plano "
                + level.title()
                + ". Experimente outro plano na página Planos."
            ),
            403,
        )


@app.before_request
def check_auth():
    public_paths = ("/login", "/api/health")
    if request.path in public_paths or request.path.startswith("/static/"):
        return None
    if "user_id" not in session:
        if request.path.startswith("/api/"):
            return jsonify(error="Faça login para acessar seus dados."), 401
        return redirect(url_for("login"))
    return None


@app.errorhandler(ValueError)
def invalid(error):
    return jsonify(error=str(error)), 400


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Envie um objeto JSON válido.")
    return data


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("Preencha o nome/descrição com até 120 caracteres.")
    return value.strip()


def categories():
    with db() as c:
        return [r[0] for r in c.execute("SELECT name FROM categories ORDER BY name")]


@app.get("/api/health")
def health():
    return jsonify(ok=True)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        with db() as c:
            user = c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["display_name"] = user["display_name"]
            return redirect(url_for("page"))
        error = "Usuário ou senha incorretos."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@app.route("/dashboard")
@app.route("/transacoes")
@app.route("/metas")
@app.route("/relatorios")
@app.route("/simulador")
@app.route("/planos")
@app.route("/assistente")
def page():
    section = request.path.strip("/") or "dashboard"
    template = {
        "metas": "metas.html",
        "simulador": "simulador.html",
        "dashboard": "dashboard.html",
    }.get(section, "index.html")
    return render_template(template, section=section, categories=categories())


@app.route("/api/categorias", methods=["GET", "POST"])
def category_api():
    if request.method == "POST":
        denied = require("plus")
        if denied:
            return denied
        name = label(payload().get("name"))
        with db() as c:
            c.execute("INSERT OR IGNORE INTO categories VALUES(?)", (name,))
    return jsonify(categories())


@app.route("/api/transacoes", methods=["GET", "POST"])
@app.route("/api/transacoes/<int:item_id>", methods=["PUT", "DELETE"])
def transactions(item_id=None):
    uid = current_user_id()
    with db() as c:
        if request.method == "GET":
            return jsonify(
                [
                    dict(r, amount=r["amount"] / 100)
                    for r in c.execute(
                        "SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC,id DESC",
                        (uid,),
                    )
                ]
            )
        if (
            item_id
            and not c.execute(
                "SELECT 1 FROM transactions WHERE id=? AND user_id=?", (item_id, uid)
            ).fetchone()
        ):
            return jsonify(error="Lançamento não encontrado."), 404
        if request.method == "DELETE":
            c.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (item_id, uid))
            return jsonify(ok=True)
        data = payload()
        kind = data.get("type")
        if kind not in ["receita", "despesa"] or data.get("category") not in categories():
            raise ValueError("Tipo ou categoria inválidos.")
        amount = money(data.get("amount"))
        if amount <= 0:
            raise ValueError("O valor precisa ser maior que zero.")
        values = (
            label(data.get("description")),
            amount,
            kind,
            data["category"],
            date.fromisoformat(str(data.get("date"))).isoformat(),
        )
        if item_id:
            c.execute(
                "UPDATE transactions SET description=?,amount=?,type=?,category=?,date=? WHERE id=? AND user_id=?",
                values + (item_id, uid),
            )
        else:
            item_id = c.execute(
                "INSERT INTO transactions(description,amount,type,category,date,user_id) VALUES(?,?,?,?,?,?)",
                values + (uid,),
            ).lastrowid
        return jsonify(id=item_id), 200 if request.method == "PUT" else 201


@app.route("/api/metas", methods=["GET", "POST"])
@app.route("/api/metas/<int:item_id>", methods=["PUT", "DELETE"])
def goals(item_id=None):
    uid = current_user_id()
    with db() as c:
        if request.method == "GET":
            result = []
            for r in c.execute("SELECT * FROM goals WHERE user_id=?", (uid,)):
                months = max(
                    1, math.ceil((date.fromisoformat(r["deadline"]) - date.today()).days / 30.4375)
                )
                result.append(
                    dict(
                        r,
                        target=r["target"] / 100,
                        saved=r["saved"] / 100,
                        monthly=max(0, r["target"] - r["saved"]) / 100 / months,
                    )
                )
            return jsonify(result)
        if (
            item_id
            and not c.execute(
                "SELECT 1 FROM goals WHERE id=? AND user_id=?", (item_id, uid)
            ).fetchone()
        ):
            return jsonify(error="Meta não encontrada."), 404
        if request.method == "DELETE":
            c.execute("DELETE FROM goals WHERE id=? AND user_id=?", (item_id, uid))
            return jsonify(ok=True)
        if (
            not item_id
            and plan() == "free"
            and c.execute("SELECT COUNT(*) FROM goals WHERE user_id=?", (uid,)).fetchone()[0] >= 1
        ):
            return (
                jsonify(error="O Free permite criar uma meta. Metas anteriores são preservadas."),
                403,
            )
        data = payload()
        target = money(data.get("target"))
        saved = money(data.get("saved", 0))
        if target <= 0 or saved > target:
            raise ValueError("Informe objetivo positivo e saldo até o valor do objetivo.")
        deadline = date.fromisoformat(str(data.get("deadline")))
        if deadline < date.today():
            raise ValueError("Escolha uma data a partir de hoje.")
        values = (label(data.get("name")), target, saved, deadline.isoformat())
        if item_id:
            c.execute(
                "UPDATE goals SET name=?,target=?,saved=?,deadline=? WHERE id=? AND user_id=?",
                values + (item_id, uid),
            )
        else:
            item_id = c.execute(
                "INSERT INTO goals(name,target,saved,deadline,user_id) VALUES(?,?,?,?,?)",
                values + (uid,),
            ).lastrowid
        return jsonify(id=item_id), 200 if request.method == "PUT" else 201


@app.get("/api/resumo")
def summary():
    uid = current_user_id()
    today = date.today()
    month = today.isoformat()[:7]
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM transactions WHERE user_id=? AND date<=?", (uid, today.isoformat())
            )
        ]
    income = (
        sum(r["amount"] for r in rows if r["type"] == "receita" and r["date"].startswith(month))
        / 100
    )
    expense = (
        sum(r["amount"] for r in rows if r["type"] == "despesa" and r["date"].startswith(month))
        / 100
    )
    series = []
    for offset in reversed(range(6)):
        year, m = divmod(today.year * 12 + today.month - 1 - offset, 12)
        key = f"{year}-{m+1:02}"
        series.append(
            {
                "month": key,
                "income": sum(
                    r["amount"]
                    for r in rows
                    if r["date"].startswith(key) and r["type"] == "receita"
                )
                / 100,
                "expense": sum(
                    r["amount"]
                    for r in rows
                    if r["date"].startswith(key) and r["type"] == "despesa"
                )
                / 100,
            }
        )
    return jsonify(
        balance=sum(r["amount"] * (1 if r["type"] == "receita" else -1) for r in rows) / 100,
        income=income,
        expense=expense,
        series=series,
        plan=plan(),
    )


@app.get("/api/relatorios")
def reports():
    denied = require("plus")
    if denied:
        return denied
    uid = current_user_id()
    with db() as c:
        rows = c.execute(
            "SELECT category,SUM(amount)/100.0 AS total FROM transactions WHERE user_id=? AND type='despesa' AND substr(date,1,7)=? AND date<=? GROUP BY category ORDER BY total DESC",
            (uid, date.today().isoformat()[:7], date.today().isoformat()),
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/ia-chat")
def chat():
    if len(request.get_data(cache=True)) > 100_000:
        return jsonify(error="Mensagem muito grande. Inicie uma nova conversa."), 413
    data = payload()
    question, history, include_context = validate_chat(data)
    streaming = data.get("stream", False)
    if not isinstance(streaming, bool):
        raise ValueError("A opção stream deve ser verdadeira ou falsa.")
    uid = current_user_id()
    context = None
    if include_context:
        connection = db()
        try:
            context = financial_context(connection, question, history, user_id=uid)
        finally:
            connection.close()
    direct = answer_from_data(question, context)
    if streaming:
        def events():
            def event(**values):
                return json.dumps(values, ensure_ascii=False) + "\n"
            try:
                yield event(source="registros" if direct else "ia", type="source")
                if direct:
                    yield event(type="token", text=direct)
                else:
                    yield from (event(type="token", text=part) for part in stream_reply(question, history, context))
                yield event(type="done")
            except LocalAIError as error:
                yield event(type="error", error=str(error), status=error.status)
        return Response(stream_with_context(events()), mimetype="application/x-ndjson",
                        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    if direct:
        return jsonify(reply=direct, source="registros")
    try:
        answer = generate_reply(question, history, context)
    except LocalAIError as error:
        return jsonify(error=str(error)), error.status
    return jsonify(reply=answer, source="ia")


@app.get("/api/ia-status")
def ai_status():
    return jsonify(local_status())


@app.post("/api/simulador")
def simulate():
    denied = require("premium")
    if denied:
        return denied
    data = payload()
    try:
        raw = float(data.get("months", 12))
        months = int(raw)
        rate = float(data.get("rate", 0)) / 100
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Prazo e taxa inválidos.")
    if raw != months or not 1 <= months <= 600 or not math.isfinite(rate) or not 0 <= rate <= 0.1:
        raise ValueError("Use 1 a 600 meses inteiros e taxa mensal entre 0 e 10%.")
    initial = money(data.get("initial", 0)) / 100
    contribution = money(data.get("monthly", 0)) / 100
    total = initial
    points = [round(total, 2)]
    for _ in range(months):
        total = total * (1 + rate) + contribution
        points.append(round(total, 2))
    invested = initial + contribution * months
    return jsonify(
        total=round(total, 2), invested=invested, interest=round(total - invested, 2), points=points
    )


@app.route("/api/plano", methods=["GET", "POST"])
def subscription():
    uid = current_user_id()
    if request.method == "POST":
        selected = payload().get("plan")
        if selected not in ["free", "plus", "premium"]:
            raise ValueError("Plano inválido.")
        with db() as c:
            c.execute("UPDATE users SET plan=? WHERE id=?", (selected, uid))
    return jsonify(plan=plan())


initialize()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
