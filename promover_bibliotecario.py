"""Concede acesso de bibliotecário a quem já tem uma conta."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Concede o perfil de bibliotecário a uma conta existente."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        ModeloUsuario = get_user_model()

        try:
            usuario = ModeloUsuario.objects.get(username=email)
        except ModeloUsuario.DoesNotExist as erro:
            raise CommandError(
                "Conta não encontrada. Cadastre-se primeiro no site."
            ) from erro

        grupo_bibliotecario = Group.objects.get(name="Bibliotecario")
        usuario.groups.add(grupo_bibliotecario)

        self.stdout.write(self.style.SUCCESS("Perfil de bibliotecário concedido."))
