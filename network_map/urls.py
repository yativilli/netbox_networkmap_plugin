from django.urls import path

from . import views

urlpatterns = [
    path('vlan-list/', views.VlanElementListView.as_view(), name='vlanelement_list'),
    path('vlan-topology/', views.VlanTopologyView.as_view(), name='vlan_topology'),
    path('vlan-connections/', views.VlanConnectionView.as_view(), name='vlan_connections'),
]