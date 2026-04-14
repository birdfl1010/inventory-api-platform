# ruff: noqa: ERA001
from django.db import models


class ProdBranchReviewFilters(models.TextChoices):
    """
    Enum for identifying filter options used in ProdBranch review workflows.
    """

    MANUAL_SETTING_REVIEW = "manual_setting_review", "Manual Settings to Review"
    # Additional filters can be added here when needed:
    # STOCK_PRODUCTS = "stock_products", "Stock Products"
    # WITH_MINIMUMS = "with_minimums", "Products with Minimums"
    # REGIONAL_LIST = "regional_stocking_list", "Regional Stocking List Products"


class ProdBranchSorting(models.TextChoices):
    """
    Enum for sorting options in ProdBranch review views or reports.
    """

    DESCRIPTION = "product_description", "Product Description"
    BUYLINE = "buyline", "Buy Line"
    PRICELINE = "priceline", "Price Line"
    COST = "cost", "Product Cost"
    DEMAND = "demand", "Monthly Demand"
    SALES = "sales_30", "30 Day Sales"
    MINIMUM = "minimum", "Manual Minimum"
    MAXIMUM = "maximum", "Manual Maximum"
    MANUAL_COST = "manual_cost", "Manual Cost"
    STOCK_FLAG_DATE = "last_stock_flag_date", "Stock Flag Date"
    MINIMUM_DATE = "last_minimum_date", "Manual Minimum Date"
    MAXIMUM_DATE = "last_maximum_date", "Manual Maximum Date"
