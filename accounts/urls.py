from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Авторизация
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('profile/', views.profile_view, name='profile'),
    
    # Социальные работники
    path('social-workers/', views.social_workers_list, name='social_workers_list'),
    path('social-workers/create/', views.social_worker_create, name='social_worker_create'),
    path('social-workers/<int:pk>/', views.social_worker_detail, name='social_worker_detail'),
    path('social-workers/<int:pk>/edit/', views.social_worker_edit, name='social_worker_edit'),
    path('social-workers/<int:pk>/delete/', views.social_worker_delete, name='social_worker_delete'),
    path('social-workers/assigned/', views.assigned_persons, name='assigned_persons'),
    path('social-workers/assigned/assign/', views.assign_recipient, name='assign_recipient'),
    path('social-workers/assigned/unassign/<int:pk>/', views.unassign_recipient, name='unassign_recipient'),
    path('medical-checkup/', views.medical_checkup_panel, name='medical_checkup_panel'),
    path('medical-checkup/mark-passed/', views.medical_checkup_mark_passed, name='medical_checkup_mark_passed'),
    path('medical-checkup/clear-mark/', views.medical_checkup_clear_mark, name='medical_checkup_clear_mark'),
    path('medical-checkup/assign/', views.medical_checkup_assign, name='medical_checkup_assign'),
    path('safety-briefing/', views.safety_briefing_panel, name='safety_briefing_panel'),
    path('safety-briefing/add/', views.safety_briefing_add, name='safety_briefing_add'),
    path('safety-briefing/<int:pk>/delete/', views.safety_briefing_delete, name='safety_briefing_delete'),
    path('safety-briefing/<int:pk>/mark-passed/', views.safety_briefing_mark_passed, name='safety_briefing_mark_passed'),
    path('safety-briefing/<int:pk>/clear-passed/', views.safety_briefing_clear_passed, name='safety_briefing_clear_passed'),

    # Получатели услуг
    path('recipients/', views.recipients_list, name='recipients_list'),
    path('recipients/create/', views.recipient_create, name='recipient_create'),
    path('recipients/<int:pk>/', views.recipient_detail, name='recipient_detail'),
    path('recipients/<int:pk>/edit/', views.recipient_edit, name='recipient_edit'),
    path('recipients/<int:pk>/delete/', views.recipient_delete, name='recipient_delete'),

    path('visits/', views.visit_planning, name='visit_planning'),
    path('visits/planned/create/', views.planned_visit_create, name='planned_visit_create'),
    path('visits/planned/<int:pk>/edit/', views.planned_visit_edit, name='planned_visit_edit'),
    path('visits/reminders/create/', views.visit_task_reminder_create, name='visit_task_reminder_create'),
    path('visits/reminders/<int:pk>/delete/', views.visit_task_reminder_delete, name='visit_task_reminder_delete'),

    # Услуги
    path('services/', views.services_panel, name='services_panel'),
    path('services/<int:worker_pk>/<int:location_pk>/', views.services_detail, name='services_detail'),
    path('services/location/create/', views.location_create, name='location_create'),
    path('services/location/<int:pk>/delete/', views.location_delete, name='location_delete'),

    # Отчёты
    path('reports/', views.report_select, name='report_select'),
    path('reports/<str:report_type>/pdf/', views.report_pdf, name='report_pdf'),
]
