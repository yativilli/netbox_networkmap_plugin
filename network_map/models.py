from django.db import models
from netbox.models import NetBoxModel
from .choices import LocationChoices, DeviceChoices

class NetworkElement(NetBoxModel):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(max_length=50, choices=DeviceChoices)
    location = models.CharField(max_length=100, choices=LocationChoices)
    role = models.CharField(max_length=50)
    tags = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=20)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

class VlanElement(NetBoxModel):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    group = models.CharField(max_length=100)
    prefix = models.CharField(max_length=60)
    status = models.CharField(max_length=20)
    role = models.CharField(max_length=50)  
    description = models.TextField(max_length=500, blank=True)