"""
leis_fetcher.py — Baixa artigos de leis federais brasileiras para o banco de dados.

Como rodar (para popular o banco):
    python3 leis_fetcher.py

Ou importe e chame buscar_todas_leis(conn) de qualquer lugar do app.
"""

import re
import sqlite3
import time

import requests
import urllib3

# Desativa avisos de SSL para sites com certificado autoassinado
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Endereços das APIs que usamos para buscar as leis
URL_API_SENADO = "https://legis.senado.leg.br/dadosabertos/legislacao/lista"
URL_LEXML      = "https://www.lexml.gov.br/urn/{urn}"

# Lista de leis que queremos baixar — adicione mais aqui se precisar
LEIS = [
    {"nome": "Código Penal",                   "tipo": "DEL", "num": "2848"},
    {"nome": "Lei de Drogas",                  "tipo": "LEI", "num": "11343"},
    {"nome": "Lei de Organizações Criminosas", "tipo": "LEI", "num": "12850"},
]

# Converte o tipo da lei (ex: "DEL") para o formato usado pelo LexML
TIPO_PARA_LEXML = {
    "DEL": "decreto.lei",
    "LEI": "lei",
    "LC":  "lei.complementar",
    "CF":  "constituicao",
    "DEC": "decreto",
    "MPV": "medida.provisoria",
}


# ── Funções de HTTP ───────────────────────────────────────────────────────────

def requisicao_get(url, tentativas=3, espera=2, **kwargs):
    # Faz uma requisição GET e tenta novamente se a rede falhar
    for tentativa in range(1, tentativas + 1):
        try:
            return requests.get(url, **kwargs)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as erro:
            if tentativa == tentativas:
                raise  # Se esgotou as tentativas, lança o erro
            print(f"    [tentativa {tentativa}/{tentativas}] {erro} — aguardando {espera}s")
            time.sleep(espera)


# ── Funções de busca nas APIs ─────────────────────────────────────────────────

def buscar_lei_na_api(tipo, numero):
    # Consulta a API do Senado e retorna os dados básicos da lei (nome, ementa, URN)
    resposta = requisicao_get(
        URL_API_SENADO,
        params={"tipo": tipo, "numero": numero},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    resposta.raise_for_status()

    documentos = resposta.json()["ListaDocumento"]["documentos"]["documento"]

    # A API às vezes retorna um único documento como dict em vez de lista
    if isinstance(documentos, dict):
        documentos = [documentos]

    doc = documentos[0]

    # O campo "norma" vem no formato "DEL-2848-1940-12-07"
    partes = doc["norma"].split("-")
    num    = partes[1]
    data   = "-".join(partes[2:])

    tipo_lexml = TIPO_PARA_LEXML.get(tipo.upper(), tipo.lower())
    urn = f"urn:lex:br:federal:{tipo_lexml}:{data};{num}"

    return {
        "urn":    urn,
        "nome":   doc["normaNome"],
        "ementa": doc.get("ementa", ""),
    }


def buscar_link_camara(urn):
    # Acessa o LexML e pega o link para o texto da lei na Câmara dos Deputados
    resposta = requisicao_get(URL_LEXML.format(urn=urn), timeout=10, verify=False)
    resposta.raise_for_status()

    # Procura um link para o arquivo HTML da lei na Câmara
    encontrado = re.search(
        r'href="(https?://www2\.camara\.(?:gov|leg)\.br/legin/[^"]*-norma-p[el]\.html)"',
        resposta.text,
    )

    if encontrado:
        return encontrado.group(1)
    return None


def buscar_texto_compilado(link_norma):
    # A Câmara tem dois arquivos: a lei original e a lei atualizada ("normaatualizada")
    # Trocamos o sufixo para pegar a versão mais recente
    link_atualizado = re.sub(r"-norma-(p[el])\.html", r"-normaatualizada-\1.html", link_norma)

    resposta = requisicao_get(link_atualizado, timeout=30, allow_redirects=True)
    resposta.raise_for_status()
    resposta.encoding = "utf-8"
    return resposta.text


# ── Funções de extração de texto ──────────────────────────────────────────────

def remover_html(html):
    # Remove todas as tags HTML e deixa só o texto limpo
    texto = re.sub(r"<[^>]+>", " ", html)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto


def extrair_artigo(texto_limpo, numero_artigo):
    # Encontra o início do artigo (ex: "Art. 5") e extrai até o próximo artigo
    inicio = re.compile(rf"Art\.\s+{numero_artigo}(?!\d)")
    fim    = re.compile(rf"Art\.\s+{numero_artigo + 1}(?!\d)")

    achou_inicio = inicio.search(texto_limpo)
    if not achou_inicio:
        return f"Artigo {numero_artigo} não encontrado."

    achou_fim = fim.search(texto_limpo, achou_inicio.end())
    if not achou_fim:
        # Se não achou o próximo artigo, pega no máximo 3000 caracteres
        return texto_limpo[achou_inicio.start():achou_inicio.start() + 3000].strip()

    return texto_limpo[achou_inicio.start():achou_fim.start()].strip()


def listar_numeros_artigos(texto_limpo):
    # Percorre o texto e coleta todos os números de artigo, sem repetir
    encontrados = re.findall(r"Art\.\s+(\d+)(?!\d)", texto_limpo)

    vistos   = set()
    ordenado = []
    for m in encontrados:
        n = int(m)
        if n not in vistos:
            vistos.add(n)
            ordenado.append(n)

    return ordenado


# ── Funções de banco de dados ─────────────────────────────────────────────────

def buscar_ou_salvar_lei(conn, tipo, numero):
    # Retorna a lei do banco. Se algum campo faltar, busca na API e salva.
    tipo = tipo.upper()

    # Garante que a lei existe na tabela (sem sobrescrever se já estiver lá)
    conn.execute("INSERT OR IGNORE INTO leis(tipo, numero) VALUES (?, ?)", (tipo, numero))
    conn.commit()

    lei = conn.execute("SELECT * FROM leis WHERE tipo=? AND numero=?", (tipo, numero)).fetchone()

    # Passo 1: buscar nome e URN na API do Senado, se ainda não temos
    if not lei["nome"]:
        print(f"[1] Buscando {tipo} {numero} na API do Senado...")
        dados = buscar_lei_na_api(tipo, numero)
        print(f"    Encontrado: {dados['nome']}")
        conn.execute(
            "UPDATE leis SET nome=?, ementa=?, urn=? WHERE tipo=? AND numero=?",
            (dados["nome"], dados["ementa"], dados["urn"], tipo, numero),
        )
        conn.commit()
        time.sleep(0.5)  # pausa para não sobrecarregar a API
        lei = conn.execute("SELECT * FROM leis WHERE tipo=? AND numero=?", (tipo, numero)).fetchone()

    # Passo 2: buscar o link da Câmara via LexML, se ainda não temos
    if not lei["legin_link"]:
        print(f"[2] Resolvendo link da Câmara via LexML...")
        link = buscar_link_camara(lei["urn"])
        if not link:
            raise RuntimeError(f"Link da Câmara não encontrado para {tipo} {numero}.")
        print(f"    Link: {link}")
        conn.execute(
            "UPDATE leis SET legin_link=? WHERE tipo=? AND numero=?", (link, tipo, numero)
        )
        conn.commit()
        time.sleep(0.5)
        lei = conn.execute("SELECT * FROM leis WHERE tipo=? AND numero=?", (tipo, numero)).fetchone()

    # Passo 3: baixar o texto completo da lei, se ainda não temos
    if not lei["compiled_html"]:
        print(f"[3] Baixando texto compilado...")
        html = buscar_texto_compilado(lei["legin_link"])
        conn.execute(
            "UPDATE leis SET compiled_html=? WHERE tipo=? AND numero=?", (html, tipo, numero)
        )
        conn.commit()
        time.sleep(0.5)
        lei = conn.execute("SELECT * FROM leis WHERE tipo=? AND numero=?", (tipo, numero)).fetchone()

    return lei


def salvar_todos_artigos(conn, lei):
    # Extrai e salva todos os artigos de uma lei no banco. Retorna quantos foram novos.
    lei_id     = lei["id"]
    texto      = remover_html(lei["compiled_html"])
    numeros    = listar_numeros_artigos(texto)

    # Pega os artigos que já estão no banco para não duplicar
    ja_salvos = set()
    for linha in conn.execute("SELECT artigo_numero FROM artigos WHERE lei_id=?", (lei_id,)).fetchall():
        ja_salvos.add(linha["artigo_numero"])

    novos = 0
    for num in numeros:
        if num in ja_salvos:
            continue  # já temos esse artigo, pula
        conteudo = extrair_artigo(texto, num)
        conn.execute(
            "INSERT OR IGNORE INTO artigos(lei_id, artigo_numero, texto) VALUES (?, ?, ?)",
            (lei_id, num, conteudo),
        )
        novos += 1

    conn.commit()
    return novos


def buscar_todas_leis(conn):
    # Percorre a lista LEIS e garante que cada uma está no banco com todos os artigos
    for lei in LEIS:
        print(f"\n{'=' * 60}")
        print(f"  {lei['nome']} ({lei['tipo']} {lei['num']})")
        print(f"{'=' * 60}")

        linha      = buscar_ou_salvar_lei(conn, lei["tipo"], lei["num"])
        novos      = salvar_todos_artigos(conn, linha)
        total      = conn.execute(
            "SELECT COUNT(*) FROM artigos WHERE lei_id=?", (linha["id"],)
        ).fetchone()[0]

        print(f"    {novos} novos artigos salvos — {total} total no banco")


# ── Ponto de entrada (rodar direto pelo terminal) ─────────────────────────────

if __name__ == "__main__":
    from app import DB_PATH, inicializar_db

    # Inicializa as tabelas e abre a conexão com o banco do app
    inicializar_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        buscar_todas_leis(conn)
    finally:
        conn.close()
