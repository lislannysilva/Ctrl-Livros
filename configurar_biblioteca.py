"""Ajuda a criar o primeiro bibliotecário. Também pode ser usada pelo terminal."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Solicita a criação do primeiro bibliotecário se ainda não houver equipe ativa."

    def handle(self, *args, **options):
        ModeloUsuario = get_user_model()
        bibliotecarios_ativos = ModeloUsuario.objects.filter(
            is_active=True,
            groups__name="Bibliotecario",
        )

        if bibliotecarios_ativos.exists():
            self.stdout.write("Biblioteca já configurada.")
            return

        self.stdout.write("Primeiro acesso: crie sua conta de bibliotecário.")
        call_command("criar_bibliotecario")
