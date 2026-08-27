from django.db import models
from netbox.models import NetBoxModel
from .choices import LocationChoices, DeviceChoices

class NetworkElement(NetBoxModel):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(max_length=50, choices=DeviceChoices)
    location = models.CharField(max_length=100, choices=LocationChoices)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"