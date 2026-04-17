from django.contrib import admin

from .models import Department, InventoryProfile, InventoryUnit


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'head')
    search_fields = ('name',)


@admin.register(InventoryProfile)
class InventoryProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'role', 'department', 'position', 'phone')
    list_filter = ('role', 'department')
    search_fields = ('full_name', 'user__username', 'phone')
    autocomplete_fields = ('user', 'department')


@admin.register(InventoryUnit)
class InventoryUnitAdmin(admin.ModelAdmin):
    list_display = ('inventory_number', 'name', 'cost', 'responsible', 'updated_at')
    list_filter = ('responsible',)
    search_fields = ('inventory_number', 'name')
    autocomplete_fields = ('responsible',)
