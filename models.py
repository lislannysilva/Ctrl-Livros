"""Descreve as informações guardadas nas tabelas do banco de dados."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Categoria(models.Model):
    """Assunto ou gênero usado para organizar os livros."""

    nome = models.CharField("Nome", max_length=80, unique=True)
    descricao = models.TextField("Descrição", blank=True)

    class Meta:
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Livro(models.Model):
    """Informações do título. As cópias físicas ficam em Exemplar."""

    nome = models.CharField("Título", max_length=200)
    autor = models.CharField("Autor", max_length=150)
    co_autor = models.CharField("Coautor", max_length=150, blank=True)
    sinopse = models.TextField("Sinopse", blank=True)

    # ForeignKey liga um registro a outro. Um livro tem uma categoria.
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.PROTECT,
        verbose_name="Categoria",
    )
    cadastrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    ativo = models.BooleanField("Visível no catálogo", default=True)

    class Meta:
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome


class Exemplar(models.Model):
    """Uma cópia física do livro, identificada por um código único."""

    class Status(models.TextChoices):
        DISPONIVEL = "disponivel", "Disponível"
        RESERVADO = "reservado", "Reservado"
        EMPRESTADO = "emprestado", "Emprestado"
        INDISPONIVEL = "indisponivel", "Indisponível"

    livro = models.ForeignKey(
        Livro,
        related_name="exemplares",
        on_delete=models.PROTECT,
    )
    codigo = models.CharField("Código do exemplar", max_length=50, unique=True)
    status = models.CharField(
        max_length=15,
        choices=Status.choices,
        default=Status.DISPONIVEL,
    )

    class Meta:
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.livro}"


class Solicitacao(models.Model):
    """Pedido feito pelo leitor. A cópia é escolhida na aprovação."""

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        APROVADA = "aprovada", "Aguardando retirada"
        RECUSADA = "recusada", "Recusada"
        CANCELADA = "cancelada", "Cancelada"
        ATENDIDA = "atendida", "Em empréstimo"
        FINALIZADA = "finalizada", "Devolvido"

    leitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    livro = models.ForeignKey(Livro, on_delete=models.PROTECT)
    exemplar = models.ForeignKey(
        Exemplar,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDENTE,
    )
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)
    motivo = models.CharField("Motivo da recusa", max_length=250, blank=True)
    atendida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="solicitacoes_gerenciadas",
        on_delete=models.PROTECT,
    )

    class Meta:
        ordering = ["-criada_em", "-pk"]
        permissions = [
            ("gerenciar_circulacao", "Pode gerenciar solicitações e empréstimos"),
        ]

        # Estas regras também são verificadas pelo banco, mesmo se houver
        # duas pessoas enviando pedidos ao mesmo tempo.
        constraints = [
            # Um leitor não pode ter dois pedidos abertos para o mesmo título.
            models.UniqueConstraint(
                fields=["leitor", "livro"],
                condition=Q(status__in=["pendente", "aprovada", "atendida"]),
                name="pedido_ativo_unico_por_leitor_livro",
            ),
            # Uma cópia não pode ficar reservada para duas pessoas.
            models.UniqueConstraint(
                fields=["exemplar"],
                condition=Q(status__in=["aprovada", "atendida"]),
                name="reserva_ativa_unica_por_exemplar",
            ),
            # Um pedido aprovado precisa indicar qual cópia foi escolhida.
            models.CheckConstraint(
                condition=(
                    ~Q(status__in=["aprovada", "atendida", "finalizada"])
                    | Q(exemplar__isnull=False)
                ),
                name="pedido_aprovado_tem_exemplar",
            ),
        ]

    def __str__(self):
        return f"{self.leitor} — {self.livro}"


class Emprestimo(models.Model):
    """Registro de retirada, prazo e devolução de uma cópia."""

    # Cada solicitação pode gerar somente um empréstimo.
    solicitacao = models.OneToOneField(
        Solicitacao,
        on_delete=models.PROTECT,
        related_name="emprestimo",
    )
    exemplar = models.ForeignKey(Exemplar, on_delete=models.PROTECT)
    leitor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
    )
    retirada_em = models.DateTimeField(default=timezone.now)
    prazo = models.DateField("Prazo de devolução")
    devolvido_em = models.DateTimeField(null=True, blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="emprestimos_registrados",
    )

    class Meta:
        ordering = ["prazo", "pk"]
        constraints = [
            # A mesma cópia só pode ter um empréstimo ainda não devolvido.
            models.UniqueConstraint(
                fields=["exemplar"],
                condition=Q(devolvido_em__isnull=True),
                name="emprestimo_ativo_unico_por_exemplar",
            ),
        ]

    @property
    def atrasado(self):
        """Permite consultar emprestimo.atrasado nas telas."""
        ainda_nao_devolvido = self.devolvido_em is None
        prazo_ja_passou = self.prazo < timezone.localdate()
        return ainda_nao_devolvido and prazo_ja_passou

    def __str__(self):
        return f"{self.exemplar.codigo} — {self.leitor}"
