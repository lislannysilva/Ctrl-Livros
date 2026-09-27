"""Define os campos que aparecem nos formulários e valida seus valores."""

from django import forms
from django.utils import timezone

from .models import Categoria, Exemplar, Livro


class FormularioLivro(forms.ModelForm):
    """Usa os campos do modelo Livro para cadastrar ou editar um título."""

    class Meta:
        model = Livro
        fields = ["nome", "autor", "co_autor", "categoria", "sinopse", "ativo"]
        widgets = {
            "sinopse": forms.Textarea(attrs={"rows": 4}),
        }


class FormularioNovoLivro(FormularioLivro):
    """No primeiro cadastro, também pergunta quantas cópias serão criadas."""

    quantidade = forms.IntegerField(
        label="Quantidade de exemplares",
        min_value=1,
        max_value=100,
        initial=1,
        help_text="Cada cópia terá um código próprio, gerado automaticamente.",
    )


class FormularioCategoria(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ["nome", "descricao"]
        widgets = {
            "descricao": forms.Textarea(attrs={"rows": 3}),
        }


class FormularioExemplar(forms.ModelForm):
    class Meta:
        model = Exemplar
        fields = ["codigo"]

    def clean_codigo(self):
        # O Django chama clean_nomeDoCampo ao validar esse campo.
        codigo = self.cleaned_data["codigo"]
        return codigo.strip().upper()


class FormularioPrazoDevolucao(forms.Form):
    prazo = forms.DateField(
        label="Devolver até",
        widget=forms.DateInput(attrs={"type": "date"}),
        input_formats=["%Y-%m-%d"],
    )

    def clean_prazo(self):
        prazo_devolucao = self.cleaned_data["prazo"]
        hoje = timezone.localdate()

        if prazo_devolucao < hoje:
            raise forms.ValidationError("O prazo não pode estar no passado.")

        return prazo_devolucao
