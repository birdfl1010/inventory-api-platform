from django.contrib import admin

from .models import BranchManualSettingLimit
from .models import BranchSizeManualSettingLimit
from .models import ChangeLog
from .models import OrderPointModelReview
from .models import ProdBranchChange
from .models import RegionProductStockingList


@admin.register(ProdBranchChange)
class ProdBranchChangeAdmin(admin.ModelAdmin):
    """Admin interface for tracking changes to ProdBranch settings."""

    list_display = (
        "prodbranch",
        "stockflag_change",
        "manual_minimum_change",
        "manual_maximum_change",
        "last_updated",
    )
    search_fields = ("prodbranch__pk",)


@admin.register(BranchSizeManualSettingLimit)
class BranchSizeManualSettingLimitAdmin(admin.ModelAdmin):
    """Admin interface for default manual setting limits by branch size."""

    list_display = ("branch_size", "default_manual_limit")
    search_fields = ("branch_size",)


@admin.register(BranchManualSettingLimit)
class BranchManualSettingLimitAdmin(admin.ModelAdmin):
    """Admin interface for manual setting limits at the individual branch level."""

    list_display = ("branch", "manual_limit", "effective_limit")
    search_fields = ("branch",)

    def effective_limit(self, obj):
        """Display the effective manual limit in the admin panel."""
        return obj.effective_limit


@admin.register(ChangeLog)
class ChangeLogAdmin(admin.ModelAdmin):
    """Admin interface for auditing changes to ProdBranch configuration."""

    list_display = (
        "prod_branch",
        "change_session_id",
        "field_name",
        "previous_value",
        "new_value",
        "changed_by",
        "timestamp",
    )


@admin.register(RegionProductStockingList)
class RegionProductStockingListAdmin(admin.ModelAdmin):
    """Admin interface for managing product stocking lists by region."""

    list_display = (
        "region",
        "product",
        "initial_stock_quantity",
    )


@admin.register(OrderPointModelReview)
class OrderPointModelReviewAdmin(admin.ModelAdmin):
    """Admin interface for reviewing order point model suggestions."""

    list_display = (
        "prodbranch",
        "new_order_point_model_flag",
        "new_order_point",
        "suggested_manual_setting_removal_flag",
        "suggested_manual_setting_removal_reason",
        "keep_manual_settings_flag",
    )
    search_fields = ("prodbranch__product__pk",)
