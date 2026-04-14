from django.contrib import admin

from .models import Branch
from .models import BranchSize
from .models import BuyLine
from .models import PriceLine
from .models import ProdBranch
from .models import Product
from .models import Region
from .models import Sales
from .models import YearMonth


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    """Admin configuration for the Region model."""

    list_display = (
        "id",
        "name",
        "slug",
        "last_updated",
    )


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    """Admin configuration for the Branch model."""

    list_display = (
        "branch",
        "branch_name",
        "division",
        "region",
        "branch_size",
        "last_updated",
    )
    search_fields = ("branch", "branch_name", "region__name")
    list_filter = ("division", "region__name", "branch_size")


@admin.register(BranchSize)
class BranchSizeAdmin(admin.ModelAdmin):
    """Admin configuration for the BranchSize model."""

    list_display = ("id", "size_description", "last_updated")
    search_fields = ("size_description",)


@admin.register(BuyLine)
class BuyLineAdmin(admin.ModelAdmin):
    """Admin configuration for the BuyLine model."""

    list_display = ("buy_line", "buy_line_name", "last_updated")
    search_fields = ("buy_line", "buy_line_name")


@admin.register(PriceLine)
class PriceLineAdmin(admin.ModelAdmin):
    """Admin configuration for the PriceLine model."""

    list_display = ("price_line", "price_line_name", "last_updated")
    search_fields = ("price_line", "price_line_name")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin configuration for the Product model."""

    list_display = (
        "product",
        "product_desc",
        "vap_flag",
        "buy_line",
        "price_line",
        "image_url",
        "search_key_words",
        "last_updated",
    )
    search_fields = ("product", "product_desc")
    list_filter = ("buy_line", "price_line")


@admin.register(ProdBranch)
class ProdBranchAdmin(admin.ModelAdmin):
    """Admin configuration for the ProdBranch model."""

    list_display = (
        "branch",
        "product",
        "rank",
        "stock_flag_binary",
        "average_cost",
        "monthly_demand",
        "manual_minimum",
        "manual_maximum",
        "calculated_manual_cost",
        "last_updated",
    )
    search_fields = ("branch__branch_name", "product__product_desc")
    list_filter = ("branch", "product")


@admin.register(YearMonth)
class YearMonthAdmin(admin.ModelAdmin):
    """Admin configuration for the YearMonth model."""

    list_display = (
        "year",
        "month",
        "time_index",
        "last_updated",
    )


@admin.register(Sales)
class SalesAdmin(admin.ModelAdmin):
    """Admin configuration for the Sales model."""

    list_display = (
        "branch",
        "product",
        "year_month",
        "quantity",
        "last_updated",
    )
    search_fields = ("branch__branch_name", "product__product_desc")
