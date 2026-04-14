from django.apps import AppConfig


class ProdbranchSettingManagementConfig(AppConfig):
    """
    Configuration class for the prodbranch_setting_management application.
    Ensures that signals are registered when the app is ready.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "prodbranch_setting_management"

    def ready(self):
        # Import signal handlers to register them with Django
        pass
