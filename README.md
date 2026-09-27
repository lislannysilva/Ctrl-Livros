
Projeto em Python, Django 5.2 e SQLite. Requer Python 3.10 ou superior.

Abra o PowerShell na pasta que contém o arquivo `manage.py`.

Se ainda não preparou o ambiente:

```powershell rodar um por vez
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
```

Para criar um bibliotecário:

```powershell
.\.venv\Scripts\python.exe manage.py criar_bibliotecario
```

Informe e-mail, nome, senha e confirmação da senha. A senha não aparece enquanto é digitada.

Para iniciar o site:

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

Acesse http://127.0.0.1:8001/ e mantenha o terminal aberto.
Para parar, pressione Ctrl+C.

