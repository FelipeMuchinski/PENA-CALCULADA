"""
app.py — Pena Calculada v1 + Login com SQLite

Como rodar:
    pip install flask
    python app.py
Abra: http://localhost:5001
"""

import os
import sqlite3
from datetime import date

from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from calculation import CalculationState, calculate, format_duration, suggest_regime

app = Flask(__name__)
app.secret_key = "pena-calculada-dev-key"

# Caminho do banco de dados (arquivo na mesma pasta do app.py)
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


# ── Banco de dados ────────────────────────────────────────────────────────────

def conectar_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
    return conn

def inicializar_db():
    with conectar_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL,
                email         TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS leis (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo          TEXT NOT NULL,
                numero        TEXT NOT NULL,
                nome          TEXT,
                ementa        TEXT,
                urn           TEXT,
                legin_link    TEXT,
                compiled_html TEXT,
                fetched_at    TEXT DEFAULT (datetime('now')),
                UNIQUE(tipo, numero)
            );
            CREATE TABLE IF NOT EXISTS artigos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                lei_id        INTEGER NOT NULL REFERENCES leis(id),
                artigo_numero INTEGER NOT NULL,
                texto         TEXT,
                fetched_at    TEXT DEFAULT (datetime('now')),
                UNIQUE(lei_id, artigo_numero)
            );
            CREATE TABLE IF NOT EXISTS calculos (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email     TEXT NOT NULL,
                reu_name       TEXT,
                process_number TEXT,
                fase1_dias     INTEGER,
                fase2_dias     INTEGER,
                fase3_anos     INTEGER,
                fase3_meses    INTEGER,
                fase3_dias_res INTEGER,
                fase3_total    INTEGER,
                regime         TEXT,
                salvo_em       TEXT DEFAULT (datetime('now'))
            );
        """)


# ── Listas de circunstâncias, agravantes, atenuantes e causas ────────────────

CIRCUNSTANCIAS_JUDICIAIS = [
    {"id": 0, "title": "Culpabilidade",          "description": "Grau de culpa ou dolo acima do normal exigível",         "icon": "⚖️", "article": "Art. 59, I"},
    {"id": 1, "title": "Antecedentes",            "description": "Registros criminais anteriores transitados em julgado",  "icon": "📋", "article": "Art. 59, II"},
    {"id": 2, "title": "Conduta Social",          "description": "Comportamento negativo no meio familiar e social",       "icon": "👥", "article": "Art. 59, III"},
    {"id": 3, "title": "Personalidade",           "description": "Características pessoais desfavoráveis do agente",       "icon": "🧠", "article": "Art. 59, IV"},
    {"id": 4, "title": "Motivos do Crime",        "description": "Motivação fútil, torpe ou moralmente reprovável",        "icon": "🎯", "article": "Art. 59, V"},
    {"id": 5, "title": "Circunstâncias",          "description": "Modo de execução agravado, local ou tempo desfavorável", "icon": "📍", "article": "Art. 59, VI"},
    {"id": 6, "title": "Consequências",           "description": "Danos causados além do estritamente necessário",         "icon": "💥", "article": "Art. 59, VII"},
    {"id": 7, "title": "Comportamento da Vítima", "description": "Vítima não contribuiu de qualquer forma para o crime",  "icon": "🛡️", "article": "Art. 59, VIII"},
]

AGRAVANTES = [
    {"id": 0, "label": "Reincidência",                               "article": "Art. 61, I"},
    {"id": 1, "label": "Motivo fútil ou torpe",                      "article": "Art. 61, II, a"},
    {"id": 2, "label": "Para facilitar outro crime",                  "article": "Art. 61, II, b"},
    {"id": 3, "label": "Traição, emboscada ou dissimulação",          "article": "Art. 61, II, c"},
    {"id": 4, "label": "Veneno, fogo, explosivo ou tortura",          "article": "Art. 61, II, d"},
    {"id": 5, "label": "Contra ascendente, descendente ou cônjuge",   "article": "Art. 61, II, e"},
    {"id": 6, "label": "Abuso de autoridade ou relação doméstica",    "article": "Art. 61, II, f"},
    {"id": 7, "label": "Contra criança, idoso ou gestante",           "article": "Art. 61, II, h"},
    {"id": 8, "label": "Violência contra a mulher (Lei 11.340/06)",   "article": "Art. 61, II, f"},
]

ATENUANTES = [
    {"id": 0, "label": "Menor de 21 ou maior de 70 anos",            "article": "Art. 65, I"},
    {"id": 1, "label": "Desconhecimento da lei",                      "article": "Art. 65, II"},
    {"id": 2, "label": "Reparação do dano antes do julgamento",       "article": "Art. 65, III, b"},
    {"id": 3, "label": "Confissão espontânea",                        "article": "Art. 65, III, d"},
    {"id": 4, "label": "Sob influência de multidão em tumulto",       "article": "Art. 65, III, e"},
    {"id": 5, "label": "Motivo de relevante valor social ou moral",   "article": "Art. 65, III, a"},
    {"id": 6, "label": "Boa conduta anterior comprovada",             "article": "Art. 65, III"},
    {"id": 7, "label": "Coação resistível ou obediência hierárquica", "article": "Art. 65, III, c"},
    {"id": 8, "label": "Atenuante inominada (circunstância favorável não prevista em lei)", "article": "Art. 66"},
]

CAUSAS_AUMENTO = [
    {"id": 0, "label": "Concurso Formal (Art. 70)",                        "fractions": ["none","1/6","1/5","1/4","1/3","1/2"]},
    {"id": 1, "label": "Crime Continuado (Art. 71)",                       "fractions": ["none","1/6","1/4","1/3","1/2","2/3"]},
    {"id": 2, "label": "Roubo c/ emprego de arma branca (Art. 157, §2)",   "fractions": ["none","1/3","1/2"]},
    {"id": 3, "label": "Arma de Fogo — Uso Permitido (Art. 157, §2-A, I)", "fractions": ["none","fixed_2/3"],
               "fractions_label": {"none": "Nenhuma", "fixed_2/3": "+2/3 (fixo)"}},
    {"id": 4, "label": "Arma de Fogo — Uso Restrito/Proibido (Art. 157, §2-A, II)", "fractions": ["none","double"],
               "fractions_label": {"none": "Nenhuma", "double": "Dobro (×2)"}},
    {"id": 5, "label": "Uso de arma de fogo (Estatuto Desarmamento, Art. 16)", "fractions": ["none","1/2","2/3","3/4"]},
]

CAUSAS_DIMINUICAO = [
    {"id": 0, "label": "Tentativa (Art. 14, par. único)",                "fractions": ["none","1/3","1/2","2/3"]},
    {"id": 1, "label": "Participação de menor importância (Art. 29, §1)","fractions": ["none","1/6","1/4","1/3"]},
    {"id": 2, "label": "Colaboração premiada (Lei 12.850/13)",           "fractions": ["none","1/3","1/2","2/3"]},
    {"id": 3, "label": "Arrependimento Posterior (Art. 16 CP)",          "fractions": ["none","1/3","1/2","2/3"]},
    {"id": 4, "label": "Tráfico Privilegiado (Art. 33, §4º Lei 11.343)","fractions": ["none","1/6","1/4","1/3","1/2","2/3"]},
]


# ── Funções auxiliares ────────────────────────────────────────────────────────

def usuario_logado():
    # Verifica se o usuário tem uma sessão ativa
    return "user_email" in session


def obter_estado_sessao():
    # Lê os dados do cálculo salvos na sessão do usuário
    s = session.get("state", {})

    estado = CalculationState()
    estado.min_years              = int(s.get("min_years", 0))
    estado.min_months             = int(s.get("min_months", 0))
    estado.max_years              = int(s.get("max_years", 0))
    estado.max_months             = int(s.get("max_months", 0))
    estado.judicial_circumstances = s.get("judicial_circumstances", [False] * 9)
    estado.aggravating            = s.get("aggravating", [False] * 9)
    estado.mitigating             = s.get("mitigating", [False] * 9)
    estado.increase_factors       = s.get("increase_factors", ["none"] * 6)
    estado.decrease_factors       = s.get("decrease_factors", ["none"] * 6)

    return estado


def fase_para_dict(fase):
    # Converte uma fase do cálculo em dicionário para o template
    return {
        "days":           fase.days,
        "years":          fase.years,
        "months":         fase.months,
        "remaining_days": fase.remaining_days,
    }


def resultado_para_dict(resultado):
    # Monta o dicionário completo com as 3 fases para enviar ao template
    return {
        "phase1":     fase_para_dict(resultado.phase1),
        "phase2":     fase_para_dict(resultado.phase2),
        "phase3":     fase_para_dict(resultado.phase3),
        "is_valid":   resultado.is_valid,
        "phase1_fmt": format_duration(resultado.phase1),
        "phase2_fmt": format_duration(resultado.phase2),
        "phase3_fmt": format_duration(resultado.phase3),
        "regime":     suggest_regime(resultado.phase3) if resultado.is_valid else "",
    }


# ── Autenticação ──────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def entrar():
    if usuario_logado():
        return redirect(url_for("inicio"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("password", "")

        with conectar_db() as conn:
            usuario = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if usuario and check_password_hash(usuario["password_hash"], senha):
            session["user_email"] = email
            session["user_name"]  = usuario["name"]
            flash(f"Bem-vindo(a), {usuario['name']}!", "success")
            return redirect(url_for("inicio"))
        else:
            flash("E-mail ou senha incorretos.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def registrar():
    if usuario_logado():
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nome  = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("password", "")

        if not nome or not email or not senha:
            flash("Preencha todos os campos.", "error")
        elif len(senha) < 6:
            flash("A senha deve ter no mínimo 6 caracteres.", "error")
        else:
            try:
                with conectar_db() as conn:
                    conn.execute(
                        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                        (nome, email, generate_password_hash(senha, method="pbkdf2:sha256"))
                    )
                flash("Conta criada! Faça login para continuar.", "success")
                return redirect(url_for("entrar"))
            except sqlite3.IntegrityError:
                flash("Este e-mail já está cadastrado.", "error")

    return render_template("register.html")


@app.route("/logout")
def sair():
    session.clear()
    flash("Você saiu da conta.", "info")
    return redirect(url_for("entrar"))


# ── Calculadora ───────────────────────────────────────────────────────────────

@app.route("/")
def inicio():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    # Define valores padrão na sessão caso o usuário seja novo
    session.setdefault("state", {})
    session.setdefault("reu_name", "")
    session.setdefault("process_number", "")

    s = session["state"]
    s.setdefault("increase_factors", ["none"] * 6)
    s.setdefault("decrease_factors", ["none"] * 6)
    s.setdefault("mitigating", [False] * 9)
    s.setdefault("aggravating", [False] * 9)
    session["state"] = s

    return render_template("index.html", step=0,
        reu_name=session.get("reu_name", ""),
        process_number=session.get("process_number", ""),
        state=s,
        user_email=session.get("user_email", ""),
    )


@app.route("/step1", methods=["POST"])
def etapa1():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    # Salva o nome do réu, número do processo e a pena mínima/máxima
    session["reu_name"]       = request.form.get("reu_name", "")
    session["process_number"] = request.form.get("process_number", "")

    s = session.get("state", {})
    s["min_years"]  = int(request.form.get("min_years", 0))
    s["min_months"] = int(request.form.get("min_months", 0))
    s["max_years"]  = int(request.form.get("max_years", 0))
    s["max_months"] = int(request.form.get("max_months", 0))
    session["state"] = s
    session.modified = True

    resultado = resultado_para_dict(calculate(obter_estado_sessao()))

    return render_template("step2.html", step=1,
        judicial_circumstances=CIRCUNSTANCIAS_JUDICIAIS,
        aggravating=AGRAVANTES,
        mitigating=ATENUANTES,
        increase_causes=CAUSAS_AUMENTO,
        decrease_causes=CAUSAS_DIMINUICAO,
        state=s,
        result=resultado,
        reu_name=session.get("reu_name", ""),
        process_number=session.get("process_number", ""),
        user_email=session.get("user_email", ""),
    )


@app.route("/step2", methods=["POST"])
def etapa2():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    s = session.get("state", {})

    # Lê quais circunstâncias judiciais foram marcadas (checkboxes)
    circunstancias = []
    for i in range(8):
        circunstancias.append(request.form.get(f"judicial_{i}") == "on")
    s["judicial_circumstances"] = circunstancias

    # Lê as agravantes marcadas
    agravantes = []
    for i in range(9):
        agravantes.append(request.form.get(f"agg_{i}") == "on")
    s["aggravating"] = agravantes

    # Lê as atenuantes marcadas
    atenuantes = []
    for i in range(9):
        atenuantes.append(request.form.get(f"mit_{i}") == "on")
    s["mitigating"] = atenuantes

    # Lê as causas de aumento e diminuição selecionadas
    causas_aumento = []
    for i in range(6):
        causas_aumento.append(request.form.get(f"inc_{i}", "none"))
    s["increase_factors"] = causas_aumento

    causas_diminuicao = []
    for i in range(6):
        causas_diminuicao.append(request.form.get(f"dec_{i}", "none"))
    s["decrease_factors"] = causas_diminuicao

    session["state"] = s
    session.modified = True

    calc      = calculate(obter_estado_sessao())
    resultado = resultado_para_dict(calc)
    hoje      = date.today().strftime("%d/%m/%Y")

    # Salva automaticamente no banco quando o cálculo é válido
    if calc.is_valid:
        with conectar_db() as conn:
            conn.execute(
                """INSERT INTO calculos
                   (user_email, reu_name, process_number,
                    fase1_dias, fase2_dias,
                    fase3_anos, fase3_meses, fase3_dias_res, fase3_total, regime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session["user_email"],
                    session.get("reu_name", ""),
                    session.get("process_number", ""),
                    calc.phase1.days,
                    calc.phase2.days,
                    calc.phase3.years,
                    calc.phase3.months,
                    calc.phase3.remaining_days,
                    calc.phase3.days,
                    suggest_regime(calc.phase3),
                )
            )

    return render_template("step3.html", step=2,
        result=resultado,
        reu_name=session.get("reu_name", ""),
        process_number=session.get("process_number", ""),
        today=hoje,
        state=s,
        judicial_circumstances=CIRCUNSTANCIAS_JUDICIAIS,
        aggravating=AGRAVANTES,
        mitigating=ATENUANTES,
        increase_causes=CAUSAS_AUMENTO,
        decrease_causes=CAUSAS_DIMINUICAO,
        user_email=session.get("user_email", ""),
    )


@app.route("/calculate", methods=["POST"])
def calcular_api():
    # Endpoint de API: recebe JSON e devolve o resultado do cálculo
    if not usuario_logado():
        return jsonify({"error": "não autorizado"}), 401

    dados = request.get_json(force=True)

    estado = CalculationState(
        min_years              = int(dados.get("min_years", 0)),
        min_months             = int(dados.get("min_months", 0)),
        max_years              = int(dados.get("max_years", 0)),
        max_months             = int(dados.get("max_months", 0)),
        judicial_circumstances = dados.get("judicial_circumstances", [False] * 9),
        aggravating            = dados.get("aggravating", [False] * 9),
        mitigating             = dados.get("mitigating", [False] * 9),
        increase_factors       = dados.get("increase_factors", ["none"] * 6),
        decrease_factors       = dados.get("decrease_factors", ["none"] * 6),
    )

    return jsonify(resultado_para_dict(calculate(estado)))


@app.route("/step2-back")
def voltar_etapa2():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    s         = session.get("state", {})
    resultado = resultado_para_dict(calculate(obter_estado_sessao()))

    return render_template("step2.html", step=1,
        judicial_circumstances=CIRCUNSTANCIAS_JUDICIAIS,
        aggravating=AGRAVANTES,
        mitigating=ATENUANTES,
        increase_causes=CAUSAS_AUMENTO,
        decrease_causes=CAUSAS_DIMINUICAO,
        state=s,
        result=resultado,
        reu_name=session.get("reu_name", ""),
        process_number=session.get("process_number", ""),
        user_email=session.get("user_email", ""),
    )


@app.route("/reset")
def reiniciar():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    # Limpa os dados do cálculo atual sem deslogar o usuário
    session.pop("state", None)
    session.pop("reu_name", None)
    session.pop("process_number", None)
    return redirect(url_for("inicio"))


@app.route("/historico")
def historico():
    if not usuario_logado():
        return redirect(url_for("entrar"))

    with conectar_db() as conn:
        calculos = conn.execute(
            "SELECT * FROM calculos WHERE user_email=? ORDER BY salvo_em DESC",
            (session["user_email"],)
        ).fetchall()

    return render_template("historico.html",
        calculos=calculos,
        result={"is_valid": False},
        state={},
        step=0,
        user_email=session.get("user_email", ""),
    )


if __name__ == "__main__":
    inicializar_db()
    print("Pena Calculada — http://localhost:5001")
    app.run(debug=True, port=5001)
