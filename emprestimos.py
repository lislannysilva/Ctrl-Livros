"""Regras para pedir, reservar, retirar e devolver livros.

As telas ficam em views.py. Este arquivo cuida das mudanças no banco.
transaction.atomic garante que uma operação seja salva por inteiro ou desfeita.
"""

from datetime import date

from django.db import transaction
from django.utils import timezone

from .models import Emprestimo, Exemplar, Livro, Solicitacao


class ErroDeEmprestimo(ValueError):
    """Mensagem que será mostrada quando uma ação não puder ser realizada."""


STATUS_COM_PEDIDO_ABERTO = [
    Solicitacao.Status.PENDENTE,
    Solicitacao.Status.APROVADA,
    Solicitacao.Status.ATENDIDA,
]


@transaction.atomic
def criar_solicitacao(leitor, id_livro):
    """Cria um pedido, desde que haja uma cópia disponível e nenhum pedido repetido."""
    livro = Livro.objects.select_for_update().get(id=id_livro)

    if not livro.ativo:
        raise ErroDeEmprestimo("Este livro está fora do catálogo.")

    pedidos_do_leitor = Solicitacao.objects.filter(
        leitor=leitor,
        livro=livro,
        status__in=STATUS_COM_PEDIDO_ABERTO,
    )
    if pedidos_do_leitor.exists():
        raise ErroDeEmprestimo("Você já tem um pedido ou empréstimo ativo deste livro.")

    exemplares_disponiveis = livro.exemplares.filter(
        status=Exemplar.Status.DISPONIVEL,
    )
    if not exemplares_disponiveis.exists():
        raise ErroDeEmprestimo("Não há exemplar disponível neste momento.")

    solicitacao = Solicitacao.objects.create(leitor=leitor, livro=livro)
    return solicitacao


@transaction.atomic
def aprovar_solicitacao(id_solicitacao, bibliotecario):
    """Reserva uma cópia física para um pedido pendente."""
    # O bloqueio evita que duas aprovações alterem o mesmo registro ao mesmo tempo.
    solicitacao = Solicitacao.objects.select_for_update().get(id=id_solicitacao)

    if solicitacao.status != Solicitacao.Status.PENDENTE:
        raise ErroDeEmprestimo("Este pedido já foi processado.")

    if not solicitacao.leitor.is_active or not solicitacao.livro.ativo:
        raise ErroDeEmprestimo("O leitor ou o livro está inativo.")

    exemplares_disponiveis = Exemplar.objects.select_for_update().filter(
        livro=solicitacao.livro,
        status=Exemplar.Status.DISPONIVEL,
    )
    exemplar = exemplares_disponiveis.order_by("id").first()

    if exemplar is None:
        raise ErroDeEmprestimo(
            "Não há exemplar disponível. O pedido continua pendente."
        )

    # A atualização só acontece se a cópia ainda estiver disponível.
    exemplares_atualizados = Exemplar.objects.filter(
        id=exemplar.id,
        status=Exemplar.Status.DISPONIVEL,
    ).update(status=Exemplar.Status.RESERVADO)

    if exemplares_atualizados == 0:
        raise ErroDeEmprestimo(
            "Este exemplar acabou de ser reservado. Tente novamente."
        )

    solicitacao.exemplar = exemplar
    solicitacao.status = Solicitacao.Status.APROVADA
    solicitacao.atendida_por = bibliotecario
    solicitacao.save()
    return solicitacao


@transaction.atomic
def recusar_solicitacao(id_solicitacao, bibliotecario, motivo):
    """Recusa um pedido e guarda o motivo para o leitor consultar."""
    solicitacao = Solicitacao.objects.select_for_update().get(id=id_solicitacao)

    if solicitacao.status != Solicitacao.Status.PENDENTE:
        raise ErroDeEmprestimo("Somente pedidos pendentes podem ser recusados.")

    motivo = motivo.strip()
    if not motivo or len(motivo) > 250:
        raise ErroDeEmprestimo("Informe o motivo da recusa, com até 250 caracteres.")

    solicitacao.status = Solicitacao.Status.RECUSADA
    solicitacao.motivo = motivo
    solicitacao.atendida_por = bibliotecario
    solicitacao.save()


@transaction.atomic
def cancelar_solicitacao(id_solicitacao, leitor):
    """Cancela um pedido do próprio leitor e libera a cópia que estava reservada."""
    solicitacao = Solicitacao.objects.select_for_update().get(
        id=id_solicitacao,
        leitor=leitor,
    )
    status_que_permite_cancelar = [
        Solicitacao.Status.PENDENTE,
        Solicitacao.Status.APROVADA,
    ]

    if solicitacao.status not in status_que_permite_cancelar:
        raise ErroDeEmprestimo("Este pedido não pode mais ser cancelado.")

    if solicitacao.exemplar_id is not None:
        exemplares_atualizados = Exemplar.objects.filter(
            id=solicitacao.exemplar_id,
            status=Exemplar.Status.RESERVADO,
        ).update(status=Exemplar.Status.DISPONIVEL)

        if exemplares_atualizados == 0:
            raise ErroDeEmprestimo("A situação do exemplar mudou. Atualize a página.")

    solicitacao.status = Solicitacao.Status.CANCELADA
    solicitacao.save()


@transaction.atomic
def registrar_retirada(id_solicitacao, bibliotecario, prazo_devolucao):
    """Transforma a reserva em empréstimo quando o leitor retira o livro."""
    solicitacao = Solicitacao.objects.select_for_update().get(id=id_solicitacao)

    if solicitacao.status != Solicitacao.Status.APROVADA:
        raise ErroDeEmprestimo("A retirada exige uma solicitação aprovada.")

    if not isinstance(prazo_devolucao, date):
        raise ErroDeEmprestimo("Informe uma data de devolução válida.")

    if prazo_devolucao < timezone.localdate():
        raise ErroDeEmprestimo("O prazo não pode estar no passado.")

    if not solicitacao.leitor.is_active:
        raise ErroDeEmprestimo("A conta do leitor está inativa.")

    exemplares_atualizados = Exemplar.objects.filter(
        id=solicitacao.exemplar_id,
        status=Exemplar.Status.RESERVADO,
    ).update(status=Exemplar.Status.EMPRESTADO)

    if exemplares_atualizados == 0:
        raise ErroDeEmprestimo("Este exemplar não está reservado.")

    emprestimo = Emprestimo.objects.create(
        solicitacao=solicitacao,
        exemplar=solicitacao.exemplar,
        leitor=solicitacao.leitor,
        prazo=prazo_devolucao,
        registrado_por=bibliotecario,
    )

    solicitacao.status = Solicitacao.Status.ATENDIDA
    solicitacao.atendida_por = bibliotecario
    solicitacao.save()
    return emprestimo


@transaction.atomic
def registrar_devolucao(id_emprestimo):
    """Encerra o empréstimo e disponibiliza a cópia para outro leitor."""
    emprestimo = Emprestimo.objects.select_for_update().get(id=id_emprestimo)

    if emprestimo.devolvido_em is not None:
        raise ErroDeEmprestimo("A devolução já foi registrada.")

    exemplares_atualizados = Exemplar.objects.filter(
        id=emprestimo.exemplar_id,
        status=Exemplar.Status.EMPRESTADO,
    ).update(status=Exemplar.Status.DISPONIVEL)

    if exemplares_atualizados == 0:
        raise ErroDeEmprestimo("A situação do exemplar mudou. Atualize a página.")

    emprestimo.devolvido_em = timezone.now()
    emprestimo.save(update_fields=["devolvido_em"])

    solicitacao = emprestimo.solicitacao
    solicitacao.status = Solicitacao.Status.FINALIZADA
    solicitacao.save()


@transaction.atomic
def alterar_disponibilidade_exemplar(id_exemplar):
    """Marca uma cópia como disponível ou indisponível para empréstimo."""
    exemplar = Exemplar.objects.select_for_update().get(id=id_exemplar)

    if exemplar.status == Exemplar.Status.DISPONIVEL:
        exemplar.status = Exemplar.Status.INDISPONIVEL
    elif exemplar.status == Exemplar.Status.INDISPONIVEL:
        exemplar.status = Exemplar.Status.DISPONIVEL
    else:
        raise ErroDeEmprestimo(
            "Exemplares reservados ou emprestados não podem ser alterados."
        )

    exemplar.save(update_fields=["status"])
