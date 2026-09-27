"""Liga cada endereço à função que atende aquela página."""

from django.urls import path

from . import views


urlpatterns = [
    # Área do leitor
    path("home/", views.listar_livros, name="catalogo"),
    path("<int:id_livro>/", views.mostrar_detalhes_livro, name="detalhe_livro"),
    path("<int:id_livro>/solicitar/", views.solicitar_emprestimo, name="solicitar"),
    path("meus-emprestimos/", views.listar_meus_emprestimos, name="meus_emprestimos"),
    path(
        "solicitacoes/<int:id_solicitacao>/cancelar/",
        views.cancelar_solicitacao,
        name="cancelar",
    ),

    # Painel e cadastro de livros
    path("gestao/", views.mostrar_painel_bibliotecario, name="painel_bibliotecario"),
    path("gestao/acervo/", views.listar_acervo_bibliotecario, name="acervo"),
    path("gestao/livros/novo/", views.cadastrar_livro, name="novo_livro"),
    path(
        "gestao/livros/<int:id_livro>/editar/",
        views.editar_livro,
        name="editar_livro",
    ),
    path("gestao/categorias/nova/", views.cadastrar_categoria, name="nova_categoria"),
    path(
        "gestao/livros/<int:id_livro>/exemplar/",
        views.adicionar_exemplar,
        name="novo_exemplar",
    ),
    path(
        "gestao/exemplares/<int:id_exemplar>/disponibilidade/",
        views.alterar_disponibilidade_exemplar,
        name="alternar_exemplar",
    ),

    # Aprovação, retirada e devolução
    path(
        "gestao/solicitacoes/<int:id_solicitacao>/aprovar/",
        views.aprovar_solicitacao,
        name="aprovar",
    ),
    path(
        "gestao/solicitacoes/<int:id_solicitacao>/recusar/",
        views.recusar_solicitacao,
        name="recusar",
    ),
    path(
        "gestao/solicitacoes/<int:id_solicitacao>/retirar/",
        views.registrar_retirada,
        name="retirar",
    ),
    path(
        "gestao/emprestimos/<int:id_emprestimo>/devolver/",
        views.registrar_devolucao,
        name="devolver",
    ),
]
