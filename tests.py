from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from . import emprestimos
from .models import Categoria, Emprestimo, Exemplar, Livro, Solicitacao

User = get_user_model()

class BibliotecaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.leitor = User.objects.create_user("leitor@example.com", email="leitor@example.com",
            first_name="Leitor", password="LivroFeliz!2026")
        cls.outro = User.objects.create_user("outro@example.com", email="outro@example.com",
            first_name="Outro", password="LivroFeliz!2026")
        cls.biblio = User.objects.create_user("equipe@example.com", email="equipe@example.com",
            first_name="Equipe", password="LivroFeliz!2026")
        cls.biblio.groups.add(Group.objects.get(name="Bibliotecario"))
        cls.leitor.groups.add(Group.objects.get(name="Leitor"))
        cls.categoria = Categoria.objects.create(nome="Literatura")
        cls.livro = Livro.objects.create(nome="Dom Casmurro", autor="Machado de Assis",
            categoria=cls.categoria, cadastrado_por=cls.biblio)
        cls.exemplar = Exemplar.objects.create(livro=cls.livro, codigo="EX-001")

    def pedido(self, leitor=None):
        return emprestimos.criar_solicitacao(leitor or self.leitor, self.livro.pk)

    def login_leitor(self):
        self.client.force_login(self.leitor)

    def test_fluxo_completo_pelas_telas(self):
        self.login_leitor()
        self.assertContains(self.client.get(reverse("catalogo")), "Dom Casmurro")
        self.assertContains(self.client.get(reverse("detalhe_livro", args=[self.livro.pk])), "Solicitar empréstimo")
        response = self.client.post(reverse("solicitar", args=[self.livro.pk]), follow=True)
        self.assertContains(response, "Aguardando análise")
        pedido = Solicitacao.objects.get()
        self.client.force_login(self.biblio)
        self.assertContains(self.client.get(reverse("painel_bibliotecario")), self.leitor.email)
        self.client.post(reverse("aprovar", args=[pedido.pk]))
        self.exemplar.refresh_from_db()
        self.assertEqual(self.exemplar.status, "reservado")
        self.assertContains(self.client.get(reverse("painel_bibliotecario"), {"aba": "retiradas"}), "Confirmar retirada")
        self.client.post(reverse("retirar", args=[pedido.pk]), {
            "prazo": (timezone.localdate() + timedelta(days=14)).isoformat()})
        emprestimo = Emprestimo.objects.get()
        self.login_leitor()
        self.assertContains(self.client.get(reverse("meus_emprestimos")), "Boa leitura!")
        self.client.force_login(self.biblio)
        self.assertContains(self.client.get(reverse("painel_bibliotecario"), {"aba": "emprestimos"}), "Confirmar devolução")
        self.client.post(reverse("devolver", args=[emprestimo.pk]))
        emprestimo.refresh_from_db()
        self.exemplar.refresh_from_db()
        pedido.refresh_from_db()
        self.assertIsNotNone(emprestimo.devolvido_em)
        self.assertEqual(self.exemplar.status, "disponivel")
        self.assertEqual(pedido.status, "finalizada")
        self.login_leitor()
        self.assertContains(self.client.get(reverse("meus_emprestimos")), "Leitura concluída")
        self.assertIsNotNone(self.pedido())

    def test_leitor_nao_acessa_funcoes_da_equipe(self):
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        emprestimo = emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())
        self.login_leitor()
        for nome in ["painel_bibliotecario", "acervo", "novo_livro", "nova_categoria"]:
            with self.subTest(nome=nome):
                self.assertEqual(self.client.get(reverse(nome)).status_code, 403)
                self.assertEqual(self.client.post(reverse(nome), {}).status_code, 403)
        for nome, pk in [
            ("aprovar", pedido.pk), ("recusar", pedido.pk), ("retirar", pedido.pk),
            ("devolver", emprestimo.pk), ("editar_livro", self.livro.pk),
            ("novo_exemplar", self.livro.pk), ("alternar_exemplar", self.exemplar.pk),
        ]:
            with self.subTest(nome=nome):
                self.assertEqual(self.client.post(reverse(nome, args=[pk]), {}).status_code, 403)
        emprestimo.refresh_from_db()
        self.assertIsNone(emprestimo.devolvido_em)

    def test_anonimo_precisa_login(self):
        for nome in ["catalogo", "meus_emprestimos", "painel_bibliotecario", "acervo"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 302)
        self.assertEqual(self.client.post(reverse("solicitar", args=[self.livro.pk])).status_code, 302)

    def test_pedido_usa_usuario_da_sessao(self):
        self.login_leitor()
        self.client.post(reverse("solicitar", args=[self.livro.pk]), {"leitor": self.outro.pk})
        self.assertEqual(Solicitacao.objects.get().leitor, self.leitor)

    def test_privacidade_e_cancelamento_alheio(self):
        pedido = self.pedido()
        Livro.objects.filter(pk=self.livro.pk).update(nome="Livro privado de teste")
        self.client.force_login(self.outro)
        self.assertNotContains(self.client.get(reverse("meus_emprestimos")), "Livro privado de teste")
        self.assertEqual(self.client.post(reverse("cancelar", args=[pedido.pk])).status_code, 404)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, "pendente")

    def test_solicitacao_duplicada_bloqueada(self):
        self.pedido()
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            self.pedido()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Solicitacao.objects.create(leitor=self.leitor, livro=self.livro)
        self.assertEqual(Solicitacao.objects.count(), 1)

    def test_livro_sem_exemplar_nao_aceita_pedido(self):
        Exemplar.objects.update(status="indisponivel")
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            self.pedido()

    def test_aprovacao_duplicada_nao_reserva_outro_exemplar(self):
        segundo = Exemplar.objects.create(livro=self.livro, codigo="EX-002")
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        segundo.refresh_from_db()
        self.assertEqual(segundo.status, "disponivel")

    def test_dois_pedidos_so_um_exemplar(self):
        primeiro = self.pedido()
        segundo = self.pedido(self.outro)
        emprestimos.aprovar_solicitacao(primeiro.pk, self.biblio)
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.aprovar_solicitacao(segundo.pk, self.biblio)
        segundo.refresh_from_db()
        self.assertEqual(segundo.status, "pendente")

    def test_cancelar_reserva_libera_exemplar(self):
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        emprestimos.cancelar_solicitacao(pedido.pk, self.leitor)
        self.exemplar.refresh_from_db()
        self.assertEqual(self.exemplar.status, "disponivel")
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())

    def test_recusa_exige_motivo_e_aparece_para_leitor(self):
        pedido = self.pedido()
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.recusar_solicitacao(pedido.pk, self.biblio, "")
        emprestimos.recusar_solicitacao(pedido.pk, self.biblio, "Exemplar em manutenção.")
        self.login_leitor()
        self.assertContains(self.client.get(reverse("meus_emprestimos")), "Exemplar em manutenção.")

    def test_retirada_duplicada_e_prazo_passado(self):
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate() - timedelta(days=1))
        emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.cancelar_solicitacao(pedido.pk, self.leitor)
        self.assertEqual(Emprestimo.objects.count(), 1)

    def test_devolucao_repetida_nao_libera_novo_emprestimo(self):
        primeiro = self.pedido()
        emprestimos.aprovar_solicitacao(primeiro.pk, self.biblio)
        antigo = emprestimos.registrar_retirada(primeiro.pk, self.biblio, timezone.localdate())
        emprestimos.registrar_devolucao(antigo.pk)
        segundo = self.pedido(self.outro)
        emprestimos.aprovar_solicitacao(segundo.pk, self.biblio)
        emprestimos.registrar_retirada(segundo.pk, self.biblio, timezone.localdate())
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.registrar_devolucao(antigo.pk)
        self.exemplar.refresh_from_db()
        self.assertEqual(self.exemplar.status, "emprestado")

    def test_atraso_aparece_nos_dois_paineis(self):
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        emprestimo = emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())
        Emprestimo.objects.filter(pk=emprestimo.pk).update(prazo=timezone.localdate() - timedelta(days=1))
        self.login_leitor()
        self.assertContains(self.client.get(reverse("meus_emprestimos")), "Devolução em atraso")
        self.client.force_login(self.biblio)
        response = self.client.get(reverse("painel_bibliotecario"), {"aba": "emprestimos", "atrasados": "1"})
        self.assertContains(response, "Dom Casmurro")
        self.assertEqual(response.context["atrasados"], 1)

    def test_get_nao_muda_dados(self):
        pedido = self.pedido()
        self.client.force_login(self.biblio)
        for nome, pk in [("aprovar", pedido.pk), ("recusar", pedido.pk),
            ("retirar", pedido.pk), ("solicitar", self.livro.pk),
            ("novo_exemplar", self.livro.pk), ("alternar_exemplar", self.exemplar.pk)]:
            self.assertEqual(self.client.get(reverse(nome, args=[pk])).status_code, 405)
        pedido.refresh_from_db()
        self.assertEqual(pedido.status, "pendente")

    def test_csrf_obrigatorio(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.leitor)
        self.assertEqual(client.post(reverse("solicitar", args=[self.livro.pk])).status_code, 403)
        self.assertEqual(Solicitacao.objects.count(), 0)

    def test_catalogo_busca_categoria_disponibilidade(self):
        outra = Livro.objects.create(nome="Outro título", autor="Outro autor",
            categoria=self.categoria, cadastrado_por=self.biblio)
        self.login_leitor()
        self.assertContains(self.client.get(reverse("catalogo"), {"q": "Machado"}), "Dom Casmurro")
        self.assertNotContains(self.client.get(reverse("catalogo"), {"q": "Machado"}), "Outro título")
        self.assertNotContains(self.client.get(reverse("catalogo"), {"disponivel": "1"}), "Outro título")
        self.assertContains(self.client.get(reverse("catalogo"), {"categoria": self.categoria.pk}), "Outro título")
        self.assertEqual(self.client.get(reverse("catalogo"), {"categoria": "invalida"}).status_code, 200)

    def test_cadastro_edicao_exemplares_e_categoria(self):
        self.client.force_login(self.biblio)
        for nome in ["novo_livro", "nova_categoria", "acervo"]:
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200)
        self.client.post(reverse("nova_categoria"), {"nome": "Ciência", "descricao": "Pesquisa"})
        self.assertTrue(Categoria.objects.filter(nome="Ciência").exists())
        response = self.client.post(reverse("novo_livro"), {
            "nome": "Novo livro", "autor": "Nova autora", "categoria": self.categoria.pk,
            "quantidade": 2, "ativo": "on", "cadastrado_por": self.leitor.pk})
        livro = Livro.objects.get(nome="Novo livro")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(livro.cadastrado_por, self.biblio)
        self.assertEqual(livro.exemplares.count(), 2)
        self.client.post(reverse("editar_livro", args=[livro.pk]), {
            "nome": "Título alterado", "autor": "Nova autora", "categoria": self.categoria.pk})
        livro.refresh_from_db()
        self.assertFalse(livro.ativo)
        self.client.post(reverse("novo_exemplar", args=[livro.pk]), {"codigo": "manual-001"})
        self.assertTrue(livro.exemplares.filter(codigo="MANUAL-001").exists())
        self.assertContains(self.client.get(reverse("detalhe_livro", args=[livro.pk])), "MANUAL-001")

    def test_exemplar_reservado_nao_pode_ser_desativado(self):
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        with self.assertRaises(emprestimos.ErroDeEmprestimo):
            emprestimos.alterar_disponibilidade_exemplar(self.exemplar.pk)

    def test_livro_oculto_nao_aparece_para_leitor(self):
        Livro.objects.filter(pk=self.livro.pk).update(ativo=False)
        self.login_leitor()
        self.assertNotContains(self.client.get(reverse("catalogo")), "Dom Casmurro")
        self.assertEqual(self.client.get(reverse("detalhe_livro", args=[self.livro.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("solicitar", args=[self.livro.pk])).status_code, 404)

    def test_rollback_preserva_exemplar_se_emprestimo_falhar(self):
        from unittest.mock import patch
        pedido = self.pedido()
        emprestimos.aprovar_solicitacao(pedido.pk, self.biblio)
        with patch("livro.emprestimos.Emprestimo.objects.create", side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                emprestimos.registrar_retirada(pedido.pk, self.biblio, timezone.localdate())
        self.exemplar.refresh_from_db()
        pedido.refresh_from_db()
        self.assertEqual(self.exemplar.status, "reservado")
        self.assertEqual(pedido.status, "aprovada")


class ConcorrenciaTests(TransactionTestCase):
    def test_duas_aprovacoes_simultaneas_nao_reservam_a_mesma_copia(self):
        biblio = User.objects.create_user("bibliotecario@example.com")
        leitores = [User.objects.create_user(f"leitor{i}@example.com") for i in range(2)]
        categoria = Categoria.objects.create(nome="Teste")
        livro = Livro.objects.create(nome="Exemplar único", autor="Autor",
            categoria=categoria, cadastrado_por=biblio)
        Exemplar.objects.create(livro=livro, codigo="UNICO")
        pedidos = [emprestimos.criar_solicitacao(leitor, livro.pk) for leitor in leitores]
        barreira = Barrier(2)
        def aprovar(pk):
            close_old_connections()
            usuario = User.objects.get(pk=biblio.pk)
            barreira.wait(timeout=10)
            try:
                emprestimos.aprovar_solicitacao(pk, usuario)
                return "aprovado"
            except emprestimos.ErroDeEmprestimo:
                return "indisponivel"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(aprovar, [pedido.pk for pedido in pedidos]))
        self.assertCountEqual(resultados, ["aprovado", "indisponivel"])
        self.assertEqual(Solicitacao.objects.filter(status="aprovada").count(), 1)
        self.assertEqual(Solicitacao.objects.filter(status="pendente").count(), 1)
