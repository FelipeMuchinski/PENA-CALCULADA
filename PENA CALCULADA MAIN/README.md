# Pena Calculada — Dosimetria Trifásica

Calculadora de dosimetria penal baseada no método trifásico do Código Penal Brasileiro (Art. 59, 61, 65 e causas de aumento/diminuição).

## Como rodar

### Pré-requisitos
- Python 3.9+
- pip

### Instalação

```bash
cd v1_com_login
pip install flask
python app.py
```

Acesse **http://localhost:5001** no navegador.

## Testando o login

O banco de dados (`users.db`) é criado automaticamente na primeira execução. Não há usuários pré-cadastrados.

1. Abra **http://localhost:5001/register**
2. Preencha nome, e-mail e senha (mínimo 6 caracteres)
3. Após o cadastro, faça login em **http://localhost:5001/login**

As senhas são armazenadas como hash `pbkdf2:sha256` — nunca em texto plano.

## Estrutura do projeto

```
v1_com_login/
├── app.py            # Rotas Flask + lógica de autenticação
├── calculation.py    # Lógica de cálculo da dosimetria
├── users.db          # Banco SQLite (gerado automaticamente, não versionado)
└── templates/
    ├── base.html     # Layout base com header, sidebar e painel
    ├── login.html    # Página de login
    ├── register.html # Página de cadastro
    ├── index.html    # Etapa 1 — configuração da pena em abstrato
    ├── step2.html    # Etapa 2 — circunstâncias e modificadores
    └── step3.html    # Etapa 3 — resultado final
```

## Rotas

| Rota | Método | Descrição |
|---|---|---|
| `/` | GET | Calculadora (requer login) |
| `/login` | GET, POST | Login |
| `/register` | GET, POST | Cadastro de novo usuário |
| `/logout` | GET | Encerra a sessão |
| `/step1` | POST | Processa pena em abstrato |
| `/step2` | POST | Processa modificadores |
| `/calculate` | POST | API de cálculo (JSON) |
| `/reset` | GET | Reinicia o cálculo |
