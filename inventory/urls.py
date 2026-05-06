from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = 'inventory'

urlpatterns = [
    path('portal/login/', RedirectView.as_view(pattern_name='inventory:login', query_string=True)),
    path('portal/register/', RedirectView.as_view(pattern_name='inventory:register', query_string=True)),
    path('portal/logout/', RedirectView.as_view(pattern_name='inventory:logout', query_string=True)),
    # Совместимость: раньше открывался экран выбора; теперь сразу форма входа, как на основном сайте.
    path('auth/', RedirectView.as_view(pattern_name='inventory:login', query_string=True), name='auth'),
    path('login/', views.inventory_login, name='login'),
    path('register/', views.inventory_register, name='register'),
    path('logout/', views.inventory_logout, name='logout'),
    path('', views.panel, name='panel'),
    path('units/', views.unit_list, name='unit_list'),
    path('units/add/', views.unit_create, name='unit_create'),
    path('units/<int:pk>/', views.unit_detail, name='unit_detail'),
    path('units/<int:pk>/edit/', views.unit_edit, name='unit_edit'),
    path('units/<int:pk>/photo/', views.unit_photo_upload, name='unit_photo_upload'),
    path('units/<int:pk>/delete/', views.unit_delete, name='unit_delete'),
    path('report.csv', views.report_csv, name='report_csv'),
    path('departments/', views.department_list, name='department_list'),
    path('departments/add/', views.department_create, name='department_create'),
    path('departments/<int:pk>/edit/', views.department_edit, name='department_edit'),
    path('staff/', views.staff_list, name='staff_list'),
    path('staff/assign-accountable/', views.assign_inventory_accountable, name='assign_accountable'),
    path('staff/add/', views.staff_create, name='staff_create'),
]
