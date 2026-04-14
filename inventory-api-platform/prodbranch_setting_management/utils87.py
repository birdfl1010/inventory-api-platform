import re

import pandas as pd
import plotly.graph_objects as go
from django.core.paginator import EmptyPage
from django.core.paginator import PageNotAnInteger
from django.core.paginator import Paginator
from django.db.models import Avg
from django.db.models import BooleanField
from django.db.models import Case
from django.db.models import CharField
from django.db.models import Count
from django.db.models import Exists
from django.db.models import F
from django.db.models import FloatField
from django.db.models import IntegerField
from django.db.models import OuterRef
from django.db.models import Q
from django.db.models import QuerySet
from django.db.models import Sum
from django.db.models import Value
from django.db.models import When
from django.db.models.functions import Coalesce
from django.db.models.functions import Greatest
from erp_core_data.models import ProdBranch
from erp_core_data.models import Region
from erp_core_data.models import Sales
from erp_core_data.models import YearMonth

from .constants import ProdBranchReviewFilters
from .constants import ProdBranchSorting
from .forms import ProdBranchEditForm
from .models import RegionProductStockingList


def apply_product_search_filter(queryset: QuerySet, search_query: str):
    """
    Apply a search filter to the queryset based on Product ID, Description,
    Model, and Keywords.

    For a ProdBranch queryset, filters are applied through the related 'product'
    fields. For a Product queryset, it directly references the fields.
    For any other model, the unfiltered queryset is returned.
    """
    if not search_query:
        return queryset

    # Remove special characters and split into words.
    sanitized_query = re.sub(r"[^\w\s]", "", search_query)
    words = sanitized_query.split()

    # Determine the model name.
    model_name = queryset.model.__name__

    query_filter = Q()
    for word in words:
        if model_name == "Product":
            # Filter directly on Product model fields
            word_filter = (
                Q(product_desc__icontains=word)
                | Q(product__iexact=word)
                | Q(vendor_model__icontains=word)
                | Q(search_key_words__icontains=f" {word} ")
            )
        elif model_name == "ProdBranch":
            # Filter via related product fields
            word_filter = (
                Q(product__product_desc__icontains=word)
                | Q(product__product__iexact=word)
                | Q(product__vendor_model__icontains=word)
                | Q(product__search_key_words__icontains=f" {word} ")
            )
        else:
            # Unknown model, return as-is
            return queryset
        query_filter &= word_filter

    return queryset.filter(query_filter)


def apply_prodbranch_review_filters(queryset: QuerySet, review_filter: str):
    """
    Apply review-related filters for manual setting review conditions.
    """
    if review_filter == ProdBranchReviewFilters.MANUAL_SETTING_REVIEW.value:
        return queryset.filter(
            Q(order_point_model__suggested_manual_setting_removal_flag=True)
            & (
                Q(order_point_model__new_order_point__gt=F("manual_minimum"))
                | (
                    Q(order_point_model__new_order_point_model_flag=False)
                    & Q(order_point__lt=F("manual_minimum"))
                )
            ),
        )
    return queryset


def get_branch_manual_limit_stats(branch):
    """
    Retrieve statistics for manual setting limits at a branch level.
    Includes stock product count, manual settings count, and effective limit.
    """
    stats_data = (
        ProdBranch.objects.filter(branch=branch)
        .select_related(
            "branch",
            "branch_size",
            "branch_size_manual_setting_limit",
            "branch_manual_setting_limit",
        )
        .prefetch_related("change_requests")
        .values("branch")
        .annotate(
            stock_products=Count(
                "id",
                filter=(
                    (
                        Q(change_requests__isnull=False)
                        & Q(change_requests__stockflag_change=True)
                    )
                    | (Q(change_requests__isnull=True) & Q(stock_flag_binary=True))
                ),
            ),
            manual_settings_count=Count(
                "id",
                filter=(
                    (
                        Q(change_requests__isnull=False)
                        & (
                            Q(change_requests__manual_minimum_change__gt=0)
                            | Q(change_requests__manual_maximum_change__gt=0)
                        )
                    )
                    | (
                        Q(change_requests__isnull=True)
                        & (Q(manual_minimum__gt=0) | Q(manual_maximum__gt=0))
                    )
                ),
            ),
            effective_limit=Coalesce(
                F("branch__branch_size__size_limit__default_manual_limit"),
                F("branch__branchmanualsettinglimit__manual_limit"),
                Value(0, output_field=IntegerField()),
            ),
        )
    )

    return (
        stats_data[0]
        if stats_data
        else {"manual_settings_count": 0, "effective_limit": 0}
    )


def apply_buyline_filter(queryset, buy_line: str):
    """Filter queryset based on product buy line."""
    if buy_line:
        return queryset.filter(product__buy_line__buy_line__icontains=buy_line)
    return queryset


def apply_priceline_filter(queryset, price_line: str):
    """Filter queryset based on product price line."""
    if price_line:
        return queryset.filter(product__price_line__price_line__icontains=price_line)
    return queryset


def apply_vap_filter(queryset, vap_filter: str):
    """If the VAP filter is set, return only products flagged as VAP."""
    if vap_filter in ["1", "true", "True"]:
        return queryset.filter(product__vap_flag=True)
    if vap_filter == "2":
        return queryset.filter(product__vap_flag=False)
    return queryset


def apply_rsl_filter(queryset, rsl_filter: str):
    """
    Filter queryset based on RSL (Regional Stocking List) presence.
    """
    region_stocking_list = RegionProductStockingList.objects.filter(
        region=OuterRef("branch__region"),
        product=OuterRef("product"),
    )
    if rsl_filter in ["1", "true", "True"]:
        return queryset.filter(Exists(region_stocking_list))
    if rsl_filter == "2":
        return queryset.filter(~Exists(region_stocking_list))
    return queryset


def apply_sorting(queryset, sort_field: str, sort_direction: str):
    """
    Order the queryset by the given sort_field.
    Use descending order if sort_direction is 'desc'.
    """
    if not sort_field:
        return queryset.order_by("-manual_cost", "-demand", "product")

    # Annotate a null-check field to control null sort behavior
    null_field_name = f"{sort_field}_isnull"
    queryset = queryset.annotate(
        **{
            null_field_name: Case(
                When(**{f"{sort_field}__isnull": True}, then=Value(1)),
                default=Value(0),
                output_field=BooleanField(),
            ),
        },
    )

    if sort_direction == "desc":
        return queryset.order_by(f"{null_field_name}", f"-{sort_field}")
    return queryset.order_by(f"-{null_field_name}", f"{sort_field}")


def filter_prodbranches(request, queryset):
    """
    Apply multiple filters from request parameters to a ProdBranch queryset.
    """
    search_query = request.GET.get("search_query", "").strip()
    review_filter = request.GET.get("review_filter", "")
    buy_line_filter = (
        request.GET.get("buy_line_filter", "").strip()
        or request.GET.get("buy_line_advanced", "").strip()
    )
    price_line_filter = (
        request.GET.get("price_line_filter", "").strip()
        or request.GET.get("price_line_advanced", "").strip()
    )
    vap_filter = request.GET.get("vap_filter", "")
    rsl_filter = request.GET.get("rsl_filter", "")

    queryset = apply_product_search_filter(queryset, search_query)
    queryset = apply_prodbranch_review_filters(queryset, review_filter)
    queryset = apply_buyline_filter(queryset, buy_line_filter)
    queryset = apply_priceline_filter(queryset, price_line_filter)
    queryset = apply_vap_filter(queryset, vap_filter)

    return apply_rsl_filter(queryset, rsl_filter)


def build_applied_filters(request):
    """
    Construct a dictionary of currently applied filters from the request.
    Includes mapping of filter keys to human-readable labels.
    """
    filters = {}

    # Process simple filters with potential alternate keys
    simple_filters = [
        ("Search", "search_query"),
        ("Buy Line", ("buy_line_filter", "buyline_advanced")),
        ("Price Line", ("price_line_filter", "priceline_advanced")),
    ]

    for label, key in simple_filters:
        if isinstance(key, tuple):
            value = (
                request.GET.get(key[0], "").strip()
                or request.GET.get(key[1], "").strip()
            )
        else:
            value = request.GET.get(key, "").strip()
        if value:
            filters[label] = value

    # Mapping filters for VAP and RSL
    def apply_mapping(param_key, mapping, label):
        value = request.GET.get(param_key, "")
        if value in mapping:
            filters[label] = mapping[value]

    apply_mapping(
        "vap_filter",
        {"1": "VAP Only", "true": "VAP Only", "True": "VAP Only", "2": "Exclude VAP"},
        "VAP",
    )
    apply_mapping(
        "rsl_filter",
        {"1": "RSL Only", "true": "RSL Only", "True": "RSL Only", "2": "Exclude RSL"},
        "RSL",
    )

    # Process review filter with exception handling
    review_filter = request.GET.get("review_filter", "")
    if review_filter:
        try:
            filters["Review"] = ProdBranchReviewFilters(review_filter).label
        except ValueError:
            filters["Review"] = review_filter

    # Process sort filter with exception handling
    sort_field = request.GET.get("sort_field", "")
    sort_direction = request.GET.get("sort_direction", "asc")
    if sort_field:
        try:
            sort_label = ProdBranchSorting(sort_field).label
        except ValueError:
            sort_label = sort_field
        filters["Sort"] = f"{sort_label} ({sort_direction})"

    return filters


def search_products_by_line_filter(queryset: QuerySet, search_query: str, field: str):
    """
    Filter the product queryset on the given field (e.g. 'buyline' or 'priceline')
    using a case-insensitive containment search.
    """
    if not search_query:
        return queryset

    # Remove special characters and split the query into words.
    sanitized_query = re.sub(r"[^\w\s]", "", search_query)
    words = sanitized_query.split()

    # Annotate a normalized field for search
    queryset = queryset.annotate(line=F(f"{field}__{field}")).values("line")

    q_obj = Q()
    for word in words:
        kwargs = {"line__icontains": word}
        q_obj &= Q(**kwargs)

    return queryset.filter(q_obj).distinct("line").order_by("line")


def generate_sales_chart(product, branch, width=400, height=200):
    """
    Generate an interactive Plotly sales chart for a product's last 6 months.

    Args:
        product: Product instance to plot.
        branch: Branch instance to filter sales.
        width: Width of the chart in pixels.
        height: Height of the chart in pixels.

    Returns:
        HTML representation of the chart (toolbar hidden).
    """
    # Get last 6 months using `time_index`
    last_6_months = YearMonth.objects.filter(
        time_index__gte=-6,
        time_index__lte=0,
    ).order_by("time_index")

    # Query sales data
    sales_data = (
        Sales.objects.filter(
            product=product,
            branch=branch,
            year_month__in=last_6_months,
        )
        .values("year_month__year", "year_month__month")
        .annotate(total_sales=Sum("quantity"))
        .order_by("year_month__time_index")
    )

    # Convert to DataFrame for plotting
    sales_dict = {
        (row["year_month__year"], row["year_month__month"]): row["total_sales"]
        for row in sales_data
    }

    sales_df = pd.DataFrame(
        {
            "year_month": [f"{ym.year}-{ym.month:02d}" for ym in last_6_months],
            "total_sales": [
                sales_dict.get((ym.year, ym.month), 0) for ym in last_6_months
            ],
            "time_index": [ym.time_index for ym in last_6_months],
        },
    )

    # Create Plotly Figure
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sales_df["year_month"],
            y=sales_df["total_sales"],
            mode="lines+markers",
            marker={"size": 5, "line": {"width": 1, "color": "DarkSlateGrey"}},
            line={"width": 1.5},
            name="Sales Trend",
        ),
    )

    # Layout Styling
    fig.update_layout(
        title="Last 6 Months Sales",
        title_font={"size": 12},
        title_x=0.5,
        title_y=0.95,
        xaxis={
            "title": "",
            "tickangle": -45,
            "showgrid": False,
            "tickfont": {"size": 9},
            "automargin": True,
        },
        yaxis={
            "title": "",
            "showgrid": True,
            "zeroline": False,
            "tickfont": {"size": 9},
            "automargin": True,
        },
        margin={"l": 5, "r": 5, "t": 15, "b": 0},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        height=height,
        width=width,
    )

    return fig.to_html(full_html=False, config={"displayModeBar": False})


def determine_stock_settings(prodbranch, committed_change):
    """
    Determines stock flag, manual minimum, manual maximum, manual cost,
     and buypacks based on pending and committed changes.

    Returns:
        A tuple of display values with their respective CSS classes.
    """
    stock_flag = prodbranch.stock_flag_binary
    manual_minimum = prodbranch.manual_minimum
    manual_maximum = prodbranch.manual_maximum
    manual_cost = prodbranch.calculated_manual_cost

    min_class, max_class, flag_class = "", "", ""

    if committed_change:
        if committed_change.stockflag_change is not None:
            stock_flag = committed_change.stockflag_change
            flag_class = "bg-success-muted"
        if committed_change.manual_minimum_change is not None:
            manual_minimum = committed_change.manual_minimum_change
            min_class = "bg-success-muted"
            manual_cost = committed_change.calculated_manual_cost
        if committed_change.manual_maximum_change is not None:
            manual_maximum = committed_change.manual_maximum_change
            max_class = "bg-success-muted"
            manual_cost = committed_change.calculated_manual_cost
        if committed_change.buy_pack_change is not None:
            buy_pack_class = "bg-success-muted"
        if committed_change.buy_pack_divisibility_change is not None:
            buy_pack_divisibility_class = "bg-success-muted"

    return (
        stock_flag,
        manual_minimum,
        manual_maximum,
        manual_cost,
        min_class,
        max_class,
        flag_class,
        buy_pack_class,
        buy_pack_divisibility_class
    )


def get_paginated_prodbranches(
    request,
    prodbranch_queryset: QuerySet,
    page_number,
    per_page=10,
):
    """
    Fetch paginated ProdBranch records with necessary annotations for display.

    Annotations include stock flags, costs, manual settings, change request flags,
    and RSL membership. Sorts the annotated queryset according to request parameters.

    Args:
        request: Django HTTP request with filter and sort parameters.
        prodbranch_queryset: Base queryset of ProdBranch objects.
        page_number: Page number to retrieve.
        per_page: Number of records per page (default: 10).

    Returns:
        A Django Paginator page object with annotated results.
    """
    region_stocking_list = RegionProductStockingList.objects.filter(
        region=OuterRef("branch__region"),
        product=OuterRef("product"),
    )

    annotated_qs = prodbranch_queryset.prefetch_related("change_requests").annotate(
        region_stock_list_flag=Exists(region_stocking_list),
        product_description=F("product__product_desc"),
        vendor_model=F("product__vendor_model"),
        buyline=F("product__buy_line"),
        priceline=F("product__price_line"),
        stock_flag=Coalesce(
            F("change_requests__stockflag_change"),
            F("stock_flag_binary"),
        ),
        last_stock_flag_date=F("last_stock_flag_change_date"),
        stock_flag_source=Case(
            When(
                change_requests__stockflag_change__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        rank_1=F("rank"),
        cost=F("average_cost"),
        demand=F("monthly_demand"),
        sales_30=F("sales_qty_30"),
        minimum=Coalesce(
            F("change_requests__manual_minimum_change"),
            F("manual_minimum"),
        ),
        last_minimum_date=F("last_manual_minimum_change_date"),
        minimum_source=Case(
            When(
                change_requests__manual_minimum_change__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        maximum=Coalesce(
            F("change_requests__manual_maximum_change"),
            F("manual_maximum"),
        ),
        last_maximum_date=F("last_manual_maximum_change_date"),
        maximum_source=Case(
            When(
                change_requests__manual_maximum_change__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        manual_cost=Coalesce(
            F("change_requests__calculated_manual_cost"),
            F("calculated_manual_cost"),
        ),
        manual_cost_source=Case(
            When(
                change_requests__manual_cost__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        product_vap_flag=F("product__vap_flag"),
        new_op_flag=F("order_point_model__new_order_point_model_flag"),
        new_op=Greatest(
            F("order_point_model__new_order_point"),
            F("order_point"),
        ),
        manual_setting_removal_flag=F(
            "order_point_model__suggested_manual_setting_removal_flag",
        ),
        manual_setting_removal_reason=F(
            "order_point_model__suggested_manual_setting_removal_reason",
        ),
        keep_manual_settings_flag=F("order_point_model__keep_manual_settings_flag"),
        buy_pack=Coalesce(
            F("change_requests__buy_pack_change"),
            F("buy_pack_qty")
        ),
        buy_pack_source=Case(
            When(
                change_requests__buy_pack_change__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        buy_pack_div=Coalesce(
            F("change_requests__buy_pack_divisibility_change"),
            F("buy_pack_divisibility_flag")
        ),
        buy_pack_div_source=Case(
            When(
                change_requests__buy_pack_divisibility_change__isnull=False,
                then=Value("ChangeRequests"),
            ),
            default=Value("ProdBranch"),
            output_field=CharField(),
        ),
        dc_purchased_flag=Case(
            When(
                purchasing_branch__branch='1098',
                then=Value(True)
            ),
            default=Value(False),
            output_field=BooleanField(),
        )
    )

    sort_field = request.GET.get("sort_field", "")
    sort_direction = request.GET.get("sort_direction", "asc")
    annotated_qs = apply_sorting(annotated_qs, sort_field, sort_direction)

    paginator = Paginator(annotated_qs, per_page)
    return paginator.get_page(page_number)


def get_prodbranch_form(prodbranch_instance):
    """
    Build a form instance for editing a single ProdBranch.

    Args:
        prodbranch_instance: The ProdBranch instance to bind.

    Returns:
        A ProdBranchEditForm prepopulated with instance data.
    """
    return ProdBranchEditForm(
        instance=prodbranch_instance,
        initial={
            "stock_flag": prodbranch_instance.stock_flag,
            "manual_minimum": prodbranch_instance.minimum,
            "manual_maximum": prodbranch_instance.maximum,
            "buy_pack": prodbranch_instance.buy_pack,
            "buy_pack_div": prodbranch_instance.buy_pack_div,
            "keep_manual_settings_flag": prodbranch_instance.keep_manual_settings_flag,
        },
    )


def get_source_class(source):
    """
    Determine CSS class based on the source of the value.

    Args:
        source: A string label such as 'ChangeRequests' or 'ProdBranch'.

    Returns:
        A CSS class string if from change request, else empty string.
    """
    if source == "ChangeRequests":
        return "bg-success-muted"
    return ""


def build_prodbranch_context(prodbranch_instance):
    """
    Build rendering context for a single ProdBranch record.

    Includes the edit form and CSS class highlights for override values.

    Args:
        prodbranch_instance: Annotated ProdBranch instance.

    Returns:
        A context dictionary with form, data, and display classes.
    """
    form = get_prodbranch_form(prodbranch_instance)
    return {
        "form": form,
        "prodbranch": prodbranch_instance,
        "flag_class": get_source_class(prodbranch_instance.stock_flag_source),
        "min_class": get_source_class(prodbranch_instance.minimum_source),
        "max_class": get_source_class(prodbranch_instance.maximum_source),
        "cost_class": get_source_class(prodbranch_instance.manual_cost_source),
        "buy_pack_class": get_source_class(prodbranch_instance.buy_pack_source),
        "buy_pack_divisibility_class": get_source_class(prodbranch_instance.buy_pack_div_source),
    }


def get_paginated_regional_stock_list(
    prodbranch_queryset: QuerySet,
    region: Region,
    page_number,
    per_page=10,
):
    """
    Fetch paginated regional stock list data for dashboard or analysis views.

    Args:
        prodbranch_queryset: Base queryset of ProdBranch items.
        region: Region instance to match against the RSL.
        page_number: Requested page number.
        per_page: Number of results per page (default: 10).

    Returns:
        A paginated object list with additional cost/RSL annotations.
    """
    # Lookup initial stock quantities for the region
    rsl_lookup = {
        r.product_id: r.initial_stock_quantity
        for r in RegionProductStockingList.objects.filter(region=region)
    }
    total_branches = region.branches.count() or 0

    # Annotate product-level metrics from ProdBranch data
    product_qs = (
        prodbranch_queryset.values(
            "product",
            "product__product_desc",
            "product__vap_flag",
        )
        .annotate(
            branches_stocking=Count("branch", distinct=True),
            branches_selling=Count("branch", distinct=True),
            total_30_day_sales=Sum("sales_qty_30"),
            avg_30_day_sale=Case(
                When(
                    branches_stocking__gt=0,
                    then=Sum("sales_qty_30") / Count("branch", distinct=True),
                ),
                default=0,
                output_field=FloatField(),
            ),
            avg_cost=Avg("average_cost"),
        )
        .order_by("-total_30_day_sales")
    )

    # Paginate result set
    paginator = Paginator(product_qs, per_page)
    try:
        products_page = paginator.page(page_number)
    except (PageNotAnInteger, EmptyPage):
        products_page = paginator.page(1)

    # Compute RSL-related cost fields for page only
    updated_products = []
    for prod in products_page.object_list:
        prod_id = prod["product"]
        rsl_flag = prod_id in rsl_lookup
        rsl_initial = rsl_lookup.get(prod_id, 0) or 0
        avg_cost = prod.get("avg_cost") or 0
        calculated_rsl_cost = (rsl_initial * avg_cost) * total_branches
        additional_rsl_cost = 0  # Placeholder for future adjustments

        prod.update(
            {
                "rsl_flag": rsl_flag,
                "rsl_initial": rsl_initial,
                "calculated_rsl_cost": calculated_rsl_cost,
                "additional_rsl_cost": additional_rsl_cost,
            },
        )
        updated_products.append(prod)

    products_page.object_list = updated_products
    return products_page
