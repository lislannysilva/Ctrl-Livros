"""Recebe os pedidos do navegador e escolhe a página que será mostrada.

As funções que começam com listar ou mostrar exibem informações.
As demais recebem um formulário e executam uma ação.
"""

from datetime import timedelta
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from . import emprestimos
from .forms import (
    FormularioCategoria,
    FormularioExemplar,
    FormularioLivro,
    FormularioNovoLivro,
    FormularioPrazoDevolucao,
)
from .models import Categoria, Emprestimo, Exemplar, Livro, Solicitacao


def mostrar_erro_de_emprestimo(request, erro):
    """Transforma um erro conhecido em uma mensagem na página."""
    if isinstance(erro, emprestimos.ErroDeEmprestimo):
        mensagem = str(erro)
    elif isinstance(erro, IntegrityError):
        mensagem = "Este pedido já foi registrado ou processado. Atualize a página."
    elif isinstance(erro, OperationalError) and "locked" in str(erro).lower():
        mensagem = "Outra operação está em andamento. Tente novamente."
    else:
        # Erros inesperados precisam aparecer no terminal para serem corrigidos.
        raise erro

    messages.error(request, mensagem)


# TELAS E AÇÕES DO LEITOR

@login_required
def listar_livros(request):
    """Mostra o catálogo e aplica os filtros escolhidos pelo leitor."""
    texto_da_busca = request.GET.get("q", "").strip()
    id_categoria = request.GET.get("categoria", "")
    somente_disponiveis = request.GET.get("disponivel")

    livros = Livro.objects.filter(ativo=True).select_related("categoria")

    # Cria uma contagem de cópias disponíveis para cada título.
    livros = livros.annotate(
        disponiveis=Count(
            "exemplares",
            filter=Q(exemplares__status=Exemplar.Status.DISPONIVEL),
        )
    )

    if texto_da_busca:
        livros = livros.filter(
            Q(nome__icontains=texto_da_busca)
            | Q(autor__icontains=texto_da_busca)
            | Q(co_autor__icontains=texto_da_busca)
            | Q(categoria__nome__icontains=texto_da_busca)
        )

    if id_categoria.isdigit():
        livros = livros.filter(categoria_id=id_categoria)

    if somente_disponiveis:
        livros = livros.filter(disponiveis__gt=0)

    livros = livros.order_by("nome", "id")
    paginador = Paginator(livros, 12)
    pagina = paginador.get_page(request.GET.get("page"))

    # Mantém a busca quando o leitor passa para a próxima página.
    filtros_da_busca = request.GET.copy()
    filtros_da_busca.pop("page", None)

    dados_da_pagina = {
        "pagina": pagina,
        "busca": texto_da_busca,
        "categorias": Categoria.objects.all(),
        "categoria_atual": id_categoria,
        "parametros": filtros_da_busca.urlencode(),
        "total": paginador.count,
    }
    return render(request, "livro/catalogo.html", dados_da_pagina)


@login_required
def mostrar_detalhes_livro(request, id_livro):
    """Exibe o livro, a disponibilidade e o pedido atual do leitor."""
    livros = Livro.objects.select_related("categoria")

    if not request.user.has_perm("livro.change_livro"):
        livros = livros.filter(ativo=True)

    livro = get_object_or_404(livros, id=id_livro)
    pedido_do_leitor = Solicitacao.objects.filter(
        leitor=request.user,
        livro=livro,
        status__in=emprestimos.STATUS_COM_PEDIDO_ABERTO,
    ).first()
    quantidade_disponivel = livro.exemplares.filter(
        status=Exemplar.Status.DISPONIVEL,
    ).count()

    dados_da_pagina = {
        "livro": livro,
        "pedido": pedido_do_leitor,
        "disponiveis": quantidade_disponivel,
        "exemplares": livro.exemplares.all(),
        "exemplar_form": FormularioExemplar(),
    }
    return render(request, "livro/detalhe.html", dados_da_pagina)


@login_required
@require_POST
def solicitar_emprestimo(request, id_livro):
    """Envia um pedido em nome da pessoa que está conectada."""
    get_object_or_404(Livro, id=id_livro, ativo=True)

    try:
        emprestimos.criar_solicitacao(request.user, id_livro)
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(
            request,
            "Solicitação enviada. Aguarde a aprovação do bibliotecário.",
        )

    return redirect("meus_emprestimos")


@login_required
def listar_meus_emprestimos(request):
    """Mostra somente os pedidos e empréstimos da pessoa conectada."""
    pedidos_do_leitor = Solicitacao.objects.filter(leitor=request.user)
    pedidos_do_leitor = pedidos_do_leitor.select_related(
        "livro", "exemplar", "emprestimo"
    )
    paginador = Paginator(pedidos_do_leitor, 20)
    pagina = paginador.get_page(request.GET.get("page"))

    return render(request, "livro/meus_emprestimos.html", {"pedidos": pagina})


@login_required
@require_POST
def cancelar_solicitacao(request, id_solicitacao):
    """Permite que o leitor cancele seu próprio pedido antes da retirada."""
    get_object_or_404(Solicitacao, id=id_solicitacao, leitor=request.user)

    try:
        emprestimos.cancelar_solicitacao(id_solicitacao, request.user)
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(request, "Solicitação cancelada.")

    return redirect("meus_emprestimos")


# PAINEL E AÇÕES DO BIBLIOTECÁRIO
# permission_required confere o acesso mesmo quando alguém digita a URL à mão.

@login_required
@permission_required("livro.gerenciar_circulacao", raise_exception=True)
def mostrar_painel_bibliotecario(request):
    """Exibe as solicitações, retiradas, empréstimos ou o histórico."""
    solicitacoes = Solicitacao.objects.select_related("livro", "leitor", "exemplar")
    emprestimos_ativos = Emprestimo.objects.filter(devolvido_em__isnull=True)
    emprestimos_ativos = emprestimos_ativos.select_related("exemplar__livro", "leitor")

    pedidos_pendentes = solicitacoes.filter(status=Solicitacao.Status.PENDENTE)
    pedidos_aprovados = solicitacoes.filter(status=Solicitacao.Status.APROVADA)
    emprestimos_atrasados = emprestimos_ativos.filter(prazo__lt=timezone.localdate())

    aba_escolhida = request.GET.get("aba", "pendentes")
    abas_permitidas = ["pendentes", "retiradas", "emprestimos", "historico"]

    if aba_escolhida not in abas_permitidas:
        aba_escolhida = "pendentes"

    if aba_escolhida == "pendentes":
        registros = pedidos_pendentes.order_by("criada_em", "id")
    elif aba_escolhida == "retiradas":
        registros = pedidos_aprovados.order_by("criada_em", "id")
    elif aba_escolhida == "emprestimos":
        registros = emprestimos_ativos
        if request.GET.get("atrasados"):
            registros = emprestimos_atrasados
    else:
        registros = solicitacoes.exclude(
            status__in=emprestimos.STATUS_COM_PEDIDO_ABERTO,
        ).select_related("emprestimo")

    paginador = Paginator(registros, 20)
    pagina = paginador.get_page(request.GET.get("page"))
    prazo_sugerido = timezone.localdate() + timedelta(days=14)

    dados_da_pagina = {
        "aba": aba_escolhida,
        "registros": pagina,
        "pendentes": pedidos_pendentes.count(),
        "retiradas": pedidos_aprovados.count(),
        "ativos": emprestimos_ativos.count(),
        "atrasados": emprestimos_atrasados.count(),
        "prazo_padrao": prazo_sugerido.isoformat(),
    }
    return render(request, "livro/painel.html", dados_da_pagina)


@login_required
@permission_required("livro.gerenciar_circulacao", raise_exception=True)
@require_POST
def aprovar_solicitacao(request, id_solicitacao):
    """Aprova o pedido escolhido no painel."""
    get_object_or_404(Solicitacao, id=id_solicitacao)

    try:
        emprestimos.aprovar_solicitacao(id_solicitacao, request.user)
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(
            request,
            "Pedido aprovado. Um exemplar foi reservado para retirada.",
        )

    return redirect("painel_bibliotecario")


@login_required
@permission_required("livro.gerenciar_circulacao", raise_exception=True)
@require_POST
def recusar_solicitacao(request, id_solicitacao):
    """Recusa o pedido usando o motivo preenchido pelo bibliotecário."""
    get_object_or_404(Solicitacao, id=id_solicitacao)
    motivo_da_recusa = request.POST.get("motivo", "")

    try:
        emprestimos.recusar_solicitacao(
            id_solicitacao,
            request.user,
            motivo_da_recusa,
        )
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(request, "Solicitação recusada.")

    return redirect("painel_bibliotecario")


@login_required
@permission_required("livro.gerenciar_circulacao", raise_exception=True)
@require_POST
def registrar_retirada(request, id_solicitacao):
    """Valida o prazo e confirma a entrega física do exemplar ao leitor."""
    get_object_or_404(Solicitacao, id=id_solicitacao)
    formulario = FormularioPrazoDevolucao(request.POST)

    if formulario.is_valid():
        prazo_devolucao = formulario.cleaned_data["prazo"]

        try:
            emprestimos.registrar_retirada(
                id_solicitacao,
                request.user,
                prazo_devolucao,
            )
        except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
            mostrar_erro_de_emprestimo(request, erro)
        else:
            messages.success(
                request,
                "Retirada registrada. O prazo já aparece na área do leitor.",
            )
    else:
        messages.error(
            request,
            "Informe uma data de devolução válida, a partir de hoje.",
        )

    return redirect("/livro/gestao/?aba=retiradas")


@login_required
@permission_required("livro.gerenciar_circulacao", raise_exception=True)
@require_POST
def registrar_devolucao(request, id_emprestimo):
    """Confirma que o exemplar foi devolvido à biblioteca."""
    get_object_or_404(Emprestimo, id=id_emprestimo)

    try:
        emprestimos.registrar_devolucao(id_emprestimo)
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(request, "Devolução registrada. Exemplar disponível.")

    return redirect("/livro/gestao/?aba=emprestimos")


# CADASTRO E ORGANIZAÇÃO DO ACERVO

@login_required
@permission_required("livro.view_livro", raise_exception=True)
def listar_acervo_bibliotecario(request):
    """Lista todos os títulos, inclusive os que estão ocultos para leitores."""
    texto_da_busca = request.GET.get("q", "").strip()
    livros = Livro.objects.select_related("categoria")
    livros = livros.annotate(total=Count("exemplares")).order_by("nome", "id")

    if texto_da_busca:
        livros = livros.filter(
            Q(nome__icontains=texto_da_busca)
            | Q(autor__icontains=texto_da_busca)
        )

    paginador = Paginator(livros, 20)
    pagina = paginador.get_page(request.GET.get("page"))
    dados_da_pagina = {"pagina": pagina, "busca": texto_da_busca}
    return render(request, "livro/acervo.html", dados_da_pagina)


@login_required
@permission_required("livro.add_livro", raise_exception=True)
@require_http_methods(["GET", "POST"])
def cadastrar_livro(request):
    """Cadastra o título e a quantidade de cópias informada no formulário."""
    if request.method == "POST":
        formulario = FormularioNovoLivro(request.POST)

        if formulario.is_valid():
            # Livro e cópias são salvos juntos. Um erro desfaz todo o cadastro.
            with transaction.atomic():
                livro = formulario.save(commit=False)
                livro.cadastrado_por = request.user
                livro.save()

                quantidade = formulario.cleaned_data["quantidade"]
                for numero_do_exemplar in range(quantidade):
                    codigo_do_exemplar = "EX-" + uuid4().hex[:12].upper()
                    Exemplar.objects.create(
                        livro=livro,
                        codigo=codigo_do_exemplar,
                    )

            messages.success(request, "Livro e exemplares cadastrados.")
            return redirect("detalhe_livro", id_livro=livro.id)
    else:
        formulario = FormularioNovoLivro()

    dados_da_pagina = {
        "form": formulario,
        "titulo": "Cadastrar livro",
        "subtitulo": "Um novo título para o acervo.",
        "categoria_atalho": True,
    }
    return render(request, "livro/form.html", dados_da_pagina)


@login_required
@permission_required("livro.change_livro", raise_exception=True)
@require_http_methods(["GET", "POST"])
def editar_livro(request, id_livro):
    """Atualiza os dados de um título que já existe."""
    livro = get_object_or_404(Livro, id=id_livro)

    if request.method == "POST":
        formulario = FormularioLivro(request.POST, instance=livro)

        if formulario.is_valid():
            formulario.save()
            messages.success(request, "Livro atualizado.")
            return redirect("detalhe_livro", id_livro=livro.id)
    else:
        formulario = FormularioLivro(instance=livro)

    dados_da_pagina = {
        "form": formulario,
        "titulo": "Editar livro",
        "subtitulo": livro.nome,
        "categoria_atalho": True,
    }
    return render(request, "livro/form.html", dados_da_pagina)


@login_required
@permission_required("livro.add_categoria", raise_exception=True)
@require_http_methods(["GET", "POST"])
def cadastrar_categoria(request):
    """Cadastra um assunto ou gênero para organizar os livros."""
    if request.method == "POST":
        formulario = FormularioCategoria(request.POST)

        if formulario.is_valid():
            try:
                with transaction.atomic():
                    formulario.save()
            except IntegrityError:
                formulario.add_error("nome", "Esta categoria já existe.")
            else:
                messages.success(request, "Categoria cadastrada.")
                return redirect("novo_livro")
    else:
        formulario = FormularioCategoria()

    dados_da_pagina = {
        "form": formulario,
        "titulo": "Cadastrar categoria",
        "subtitulo": "Organize o acervo por temas.",
    }
    return render(request, "livro/form.html", dados_da_pagina)


@login_required
@permission_required("livro.add_exemplar", raise_exception=True)
@require_POST
def adicionar_exemplar(request, id_livro):
    """Acrescenta uma cópia física a um título já cadastrado."""
    livro = get_object_or_404(Livro, id=id_livro)
    formulario = FormularioExemplar(request.POST)

    if formulario.is_valid():
        try:
            with transaction.atomic():
                exemplar = formulario.save(commit=False)
                exemplar.livro = livro
                exemplar.save()
        except IntegrityError:
            messages.error(request, "Esse código já pertence a outro exemplar.")
        else:
            messages.success(request, "Exemplar adicionado.")
    else:
        messages.error(request, "Informe um código único, com até 50 caracteres.")

    return redirect("detalhe_livro", id_livro=livro.id)


@login_required
@permission_required("livro.change_exemplar", raise_exception=True)
@require_POST
def alterar_disponibilidade_exemplar(request, id_exemplar):
    """Disponibiliza uma cópia ou a retira temporariamente de circulação."""
    exemplar = get_object_or_404(Exemplar, id=id_exemplar)

    try:
        emprestimos.alterar_disponibilidade_exemplar(id_exemplar)
    except (emprestimos.ErroDeEmprestimo, IntegrityError, OperationalError) as erro:
        mostrar_erro_de_emprestimo(request, erro)
    else:
        messages.success(request, "Disponibilidade atualizada.")

    return redirect("detalhe_livro", id_livro=exemplar.livro_id)
