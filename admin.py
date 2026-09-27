from django.contrib import admin
from .models import Categoria, Emprestimo, Exemplar, Livro, Solicitacao

class ConsultaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

for model in [Categoria, Livro, Exemplar, Solicitacao, Emprestimo]:
    admin.site.register(model, ConsultaAdmin)

admin.site.site_header = "Biblioteca · Administração"
admin.site.site_title = "Biblioteca"

