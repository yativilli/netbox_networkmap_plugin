from django.urls import path

from . import views

urlpatterns = (
    path('vlan-list/', views.VlanElementListView.as_view(), name='vlanelement_list'),
    path('topology/', views.NetworkElementTopologyView.as_view(), name='networkelement_topology'),
)