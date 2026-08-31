from django.urls import path

from . import models, views

urlpatterns = (
    # NetworkElement URLs
    path('list/', views.NetworkElementListView.as_view(), name='networkelement_list'),
    path('vlan-list/', views.VlanElementListView.as_view(), name='vlanelement_list'),
    path('topology/', views.NetworkElementTopologyView.as_view(), name='networkelement_topology'),
)