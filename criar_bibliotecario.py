"""Comando do terminal: python manage.py criar_bibliotecario."""

from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction


class Command(BaseCommand):
    help = "Cria uma conta de bibliotecário, sem senha padrão e sem acesso de administrador."

    # Command, add_arguments e handle são nomes exigidos pelo Django.
    def add_arguments(self, parser):
        parser.add_argument("--email")
        parser.add_argument("--nome")

    def handle(self, *args, **options):
        # 1. Lê os dados recebidos por argumento ou digitados no terminal.
        email = options["email"]
        if not email:
            email = input("E-mail: ")
        email = email.strip().lower()

        nome = options["nome"]
        if not nome:
            nome = input("Nome: ")
        nome = nome.strip()

        # 2. Valida o formato e verifica se já existe uma conta.
        try:
            validate_email(email)
        except ValidationError as erro:
            raise CommandError("Informe um e-mail válido.") from erro

        if len(email) > 150 or not nome or len(nome) > 150:
            raise CommandError("Nome e e-mail devem ter até 150 caracteres.")

        ModeloUsuario = get_user_model()
        email_ja_cadastrado = ModeloUsuario.objects.filter(
            username__iexact=email,
        ).exists()

        if email_ja_cadastrado:
            raise CommandError(
                "Conta já existe. Use promover_bibliotecario para conceder acesso."
            )

        usuario = ModeloUsuario(
            username=email,
            email=email,
            first_name=nome,
        )

        # 3. Pede e valida a senha. getpass não mostra os caracteres digitados.
        senha = getpass("Senha: ")
        confirmacao_da_senha = getpass("Repita a senha: ")

        if senha != confirmacao_da_senha:
            raise CommandError("As senhas não coincidem.")

        try:
            validate_password(senha, usuario)
        except ValidationError as erro:
            raise CommandError(" ".join(erro.messages)) from erro

        # 4. Salva a conta e concede as permissões de bibliotecário.
        with transaction.atomic():
            usuario.set_password(senha)
            usuario.save()

            grupo_bibliotecario = Group.objects.get(name="Bibliotecario")
            usuario.groups.add(grupo_bibliotecario)

        mensagem = "Bibliotecário criado. Entre pelo login do site."
        self.stdout.write(self.style.SUCCESS(mensagem))
