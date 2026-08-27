from utilities.choices import ChoiceSet

class LocationChoices(ChoiceSet):
    Location1 = "Location1"
    Location2 = "Location2"

    CHOICES = [
        (Location1, "Location 1"),
        (Location2, "Location 2")
    ]
class DeviceChoices(ChoiceSet):
    Router = "Router"
    Switch = "Switch"
    Firewall = "Firewall"

    CHOICES = [
        (Router, "Router"),
        (Switch, "Switch"),
        (Firewall, "Firewall")
    ]