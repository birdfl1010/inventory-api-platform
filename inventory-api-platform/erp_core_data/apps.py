from django.apps import AppConfig


class ErpCoreDataConfig(AppConfig):
    """
    Configuration class for the 'erp_core_data' application.
    Sets default auto field and provides a human-readable verbose name.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "erp_core_data"
    verbose_name = "ERP Core Data"
