from django.contrib import admin
from .models import (
    SocialWorker,
    ServiceRecipient,
    ServiceLocation,
    PlannedVisit,
    VisitTaskReminder,
    SafetyBriefingRecord,
    WorkloadRecord,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'updated_at')
    search_fields = ('user__username', 'user__email')
    raw_id_fields = ('user',)


@admin.register(SafetyBriefingRecord)
class SafetyBriefingRecordAdmin(admin.ModelAdmin):
    list_display = ('briefing_date', 'briefing_title', 'social_worker', 'passed', 'created_at')
    list_filter = ('briefing_date', 'passed')
    search_fields = ('briefing_title', 'notes', 'social_worker__last_name', 'social_worker__first_name')
    autocomplete_fields = ('social_worker',)
    date_hierarchy = 'briefing_date'


@admin.register(VisitTaskReminder)
class VisitTaskReminderAdmin(admin.ModelAdmin):
    list_display = ('task_date', 'social_worker', 'recipient', 'created_at')
    list_filter = ('task_date', 'social_worker')
    search_fields = ('description', 'recipient__last_name', 'recipient__first_name')
    autocomplete_fields = ('social_worker', 'recipient')
    date_hierarchy = 'task_date'


@admin.register(PlannedVisit)
class PlannedVisitAdmin(admin.ModelAdmin):
    list_display = ('visit_date', 'visit_time', 'recipient', 'social_worker', 'updated_at')
    list_filter = ('visit_date', 'social_worker')
    search_fields = ('recipient__last_name', 'recipient__first_name', 'notes')
    autocomplete_fields = ('recipient', 'social_worker')
    date_hierarchy = 'visit_date'


@admin.register(SocialWorker)
class SocialWorkerAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'get_full_name', 'birth_date', 'address', 'phone', 'medical_checkup', 'status', 'hire_date')
    list_filter = ('status', 'medical_checkup', 'hire_date')
    search_fields = ('first_name', 'last_name', 'middle_name', 'employee_id', 'phone', 'address')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Персональная информация', {
            'fields': ('first_name', 'last_name', 'middle_name', 'birth_date')
        }),
        ('Контактная информация', {
            'fields': ('phone', 'address')
        }),
        ('Рабочая информация', {
            'fields': (
                'employee_id', 'medical_panel_registered', 'medical_checkup',
                'last_medical_checkup_date', 'medical_checkup_planned_date', 'medical_notes',
                'status', 'hire_date', 'user',
            )
        }),
        ('Дополнительно', {
            'fields': ('notes',)
        }),
        ('Метаданные', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = 'ФИО'


@admin.register(ServiceRecipient)
class ServiceRecipientAdmin(admin.ModelAdmin):
    list_display = (
        'employee_id', 'get_full_name', 'birth_date', 'phone', 'address', 'disability_group',
        'payment_percent', 'visit_frequency', 'living_status',
        'admission_date', 'visit_days', 'fire_detector_count', 'social_worker', 'location'
    )
    list_filter = ('disability_group', 'living_status', 'visit_frequency', 'social_worker', 'location')
    search_fields = ('employee_id', 'first_name', 'last_name', 'middle_name', 'address', 'phone')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Персональная информация', {
            'fields': ('employee_id', 'first_name', 'last_name', 'middle_name', 'birth_date', 'phone', 'address')
        }),
        ('Обслуживание', {
            'fields': (
                'disability_group', 'payment_percent', 'visit_frequency',
                'living_status', 'admission_date', 'visit_days', 'fire_detector_count'
            )
        }),
        ('Назначение', {
            'fields': ('social_worker', 'location', 'housing_type', 'visit_planning_panel_registered')
        }),
        ('Дополнительно', {
            'fields': ('notes',)
        }),
        ('Метаданные', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = 'ФИО'


@admin.register(ServiceLocation)
class ServiceLocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'location_type')
    list_filter = ('location_type',)
    search_fields = ('name',)


@admin.register(WorkloadRecord)
class WorkloadRecordAdmin(admin.ModelAdmin):
    list_display = (
        'period_year', 'period_month', 'social_worker', 'location',
        'worked_minutes_month', 'load_coefficient', 'rate',
    )
    list_filter = ('period_year', 'period_month', 'housing_type')
    search_fields = (
        'social_worker__last_name', 'social_worker__first_name',
        'recipient__last_name', 'notes',
    )
    autocomplete_fields = ('social_worker', 'recipient', 'location')
    readonly_fields = (
        'worked_minutes_month', 'worked_hours_month', 'load_coefficient', 'rate',
        'visits_per_month', 'created_at', 'updated_at',
    )
