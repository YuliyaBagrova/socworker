from django.contrib import admin

from .models import Department, InvRole, InventoryUnit


@admin.register(InvRole)
class InvRoleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')
    search_fields = ('code', 'name')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'head')
    search_fields = ('name',)


@admin.register(InventoryUnit)
class InventoryUnitAdmin(admin.ModelAdmin):
    list_display = ('inventory_number', 'name', 'cost', 'responsible', 'updated_at')
    list_filter = ('responsible',)
    search_fields = ('inventory_number', 'name')
    autocomplete_fields = ('responsible',)
