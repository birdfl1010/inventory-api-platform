from django.urls import path
from django.views.generic import TemplateView

from .views import branch_manual_settings_view
from .views import calculate_manual_settings_cost
from .views import edit_prod_branches
from .views import edit_regional_stock_list
from .views import load_applied_filters
from .views import load_formset_rows
from .views import load_pagination_controls
from .views import load_regional_pagination_controls
from .views import load_regional_stock_list_rows
from .views import manual_limit_delete
from .views import region_branches_stocking_product
from .views import regional_metrics
from .views import regional_stock_list_base
from .views import sales_chart_view
from .views import search_line_options
from .views import search_prod_branch_form
from .views import search_prod_branch_options
from .views import stock_settings_base
from .views import stock_settings_edit
from .views import stock_settings_stats
from .views import update_prodbranch_change
from .views import update_regional_stock_list

app_name = "prodbranch_setting_management"

urlpatterns = [
    path("", branch_manual_settings_eclipse_view, name="branch_settings_list"),
#   path("", branch_manual_settings_view, name="branch_settings_list"),
    path(
        "branch-help/",
        TemplateView.as_view(
            template_name="prodbranch_setting_management/partials/branch_settings_list_help.html",
        ),
        name="branch_setting_help",
    ),
    path("stock-settings/<branch>/", stock_settings_base, name="stock_settings"),
    path(
        "stock-settings-stats/<branch>/",
        stock_settings_stats,
        name="stock_settings_stats",
    ),
    path(
        "calculate-manual-settings-cost/<int:prod_branch_id>/",
        calculate_manual_settings_cost,
        name="calculate_manual_settings_cost",
    ),
    path(
        "stock-settings-edit/<int:prod_branch_id>/",
        stock_settings_edit,
        name="stock_settings_edit",
    ),
    path(
        "search-prod-branch_form/<int:branch>/",
        search_prod_branch_form,
        name="search_prod_branch_form",
    ),
    path(
        "search-prod-branch_options/<int:branch>/",
        search_prod_branch_options,
        name="search_prod_branch_options",
    ),
    path(
        "search_line_options/<str:line_type>/<int:branch>/",
        search_line_options,
        name="search_line_options",
    ),
    path(
        "manual_limit_delete/<int:branch>/",
        manual_limit_delete,
        name="manual_limit_delete",
    ),
    path(
        "sales-chart/<int:product>/<int:branch>",
        sales_chart_view,
        name="sales_chart",
    ),
    path(
        "edit-prod-branches/<int:branch>/",
        edit_prod_branches,
        name="edit_prod_branches",
    ),
    path(
        "manual_settings/update-pending-change/<int:prodbranch_id>/",
        update_prodbranch_change,
        name="update_pending_change",
    ),
    path(
        "load-formset-rows/<int:branch>/",
        load_formset_rows,
        name="load_formset_rows",
    ),
    path(
        "load-pagination-controls/<int:branch>/",
        load_pagination_controls,
        name="load_pagination_controls",
    ),
    path(
        "load-applied-filters/",
        load_applied_filters,
        name="load_applied_filters",
    ),
    path(
        "regional-stock-list/",
        regional_metrics,
        name="regional_stock_list",
    ),
    path(
        "regional-stock-list-stocking-branches/<slug:region_slug>/<int:product_id>/",
        region_branches_stocking_product,
        name="regional_stock_list_branches_stocking",
    ),
    path(
        "regional-stock-list-base/<slug:region_slug>/",
        regional_stock_list_base,
        name="regional_stock_list_base",
    ),
    path(
        "regional-stock-list-edit/<slug:region_slug>/",
        edit_regional_stock_list,
        name="edit_regional_stock_list",
    ),
    path(
        "regional-stock-rows/<slug:region_slug>/",
        load_regional_stock_list_rows,
        name="load_regional_stock_list_rows",
    ),
    path(
        "regional-stock-pagination/<slug:region_slug>/",
        load_regional_pagination_controls,
        name="load_regonal_stock_list_pagination_controls",
    ),
    path(
        "manual_settings/update-regional-stock-list/<slug:region_slug>/<int:product_id>/",
        update_regional_stock_list,
        name="update_pending_change",
    ),
]
