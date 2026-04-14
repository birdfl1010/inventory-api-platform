import uuid
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count
from django.db.models import ExpressionWrapper
from django.db.models import F
from django.db.models import FloatField
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import Sum
from django.db.models import Value
from django.db.models.functions import Coalesce
from django.db.models.functions import Concat
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from erp_core_data.models import Branch
from erp_core_data.models import ProdBranch
from erp_core_data.models import Product
from erp_core_data.models import Region
from inventory_stock_management.users.models import UserBranchAccess
from .constants import ProdBranchReviewFilters
from .constants import ProdBranchSorting
from .forms import ProdBranchEditForm
from .models import OrderPointModelReview
from .models import ProdBranchChange
from .models import RegionProductStockingList
from .utils import apply_product_search_filter
from .utils import build_applied_filters
from .utils import build_prodbranch_context
from .utils import filter_prodbranches
from .utils import generate_sales_chart
from .utils import get_branch_manual_limit_stats
from .utils import get_paginated_prodbranches
from .utils import get_paginated_regional_stock_list
from .utils import search_products_by_line_filter

logger = logger.getLogger(__name__)


def generate_pkce():
    verifier = base64.urlsafe_b64encode(os.urandom(40)).rstrip(b'=').decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b'=').decode()
    return verifier, challenge


class OktaLogoutView(View):
    """
    Logs out the user from Django and redirects to Okta's logout endpoint (or to local URL in dev).
    """
    http_method_names = ["post"]

    @method_decorator(csrf_protect)
    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        logger.debug(f"BIRD OktaLogoutView: POST request received for user {request.user}")

        # Grab id_token BEFORE session flush
        id_token = request.session.get("oidc_id_token")
        logger.debug(f"Okta id_token retrieved: {id_token}")

        # Log out from Django
        django_logout(request)
        logger.debug("Django logout successful.")

        # Remove OIDC session data
        for key in ['oidc_id_token', 'oidc_access_token', 'oidc_token_data']:
            removed = request.session.pop(key, None)
            logger.debug(f"Okta Session cleanup: removed {key} = {removed}")

        request.session.flush()
        logger.debug("Okta Session flushed completely.")

        # Prepare redirect
        logout_redirect = self.get_success_url()
        logger.debug(f"Okta Logout redirect URL resolved to: {logout_redirect}")

        okta_logout_endpoint = getattr(settings, "OIDC_OP_LOGOUT_ENDPOINT", None)

        if okta_logout_endpoint:
            params = {
                "post_logout_redirect_uri": logout_redirect,
            }

            if id_token:
                params["id_token_hint"] = id_token

            okta_logout_url = f"{okta_logout_endpoint}?{urlencode(params)}"
            return HttpResponseRedirect(okta_logout_url)

        logger.debug("OIDC_OP_LOGOUT_ENDPOINT not set. Redirecting locally.")
        return HttpResponseRedirect(logout_redirect)

    def get_success_url(self):
        resolved = resolve_url(getattr(settings, "LOGOUT_REDIRECT_URL", "/accounts/login"))
        return resolved


def okta_login(request):
    verifier, challenge = generate_pkce()
    state = base64.urlsafe_b64encode(os.urandom(16)).decode()
    request.session['pkce_verifier'] = verifier
    request.session['pkce_state'] = state

    params = {
        "client_id": os.getenv("OKTA_CLIENT_ID"),
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": os.getenv("OKTA_REDIRECT_URI"),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    okta_domain = os.getenv("OKTA_DOMAIN")
    if not okta_domain:
        raise Exception("Missing OKTA_DOMAIN environment variable")

    auth_url = f"{okta_domain}authorize?" + urllib.parse.urlencode(params)
    logger.debug(f"Okta Login Auth URL: {auth_url}")
    return redirect(auth_url)


def okta_callback(request):
    code = request.GET.get("code")
    state = request.GET.get("state")
    error = request.GET.get("error")
    error_description = request.GET.get("error_description")

    if error:
        context = {"error": error, "description": error_description}
        if request.headers.get("HX-Request") == "true":
            html = render_to_string("account/auth_error.html", context)
            return HttpResponse(html)
        return render(request, "account/auth_error.html", context)

    # Verify PKCE state
    saved_state = request.session.get("pkce_state")
    verifier = request.session.get("pkce_verifier")
    if state != saved_state:
        return HttpResponse("Invalid state", status=400)

    okta_domain = os.getenv("OKTA_DOMAIN")
    if not okta_domain:
        raise Exception("Missing OKTA_DOMAIN environment variable")

    # Exchange code for token
    # token_url = f"{okta_domain}token"
    token_url = "https://morsco.okta.com/oauth2/default/v1/token/"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": os.getenv("OKTA_REDIRECT_URI"),
        "client_id": os.getenv("OKTA_CLIENT_ID"),
        "client_secret": os.getenv("OKTA_CLIENT_SECRET"),
        "code_verifier": verifier,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded"
    }

    logger.debug(f"Okta Call Data {data}")
    resp = requests.post(token_url, data=data, headers=headers)
    logger.debug(f"Okta Resp {resp}")
    token_data = resp.json()

    id_token = token_data["id_token"]
    access_token = token_data.get("access_token")

    if not id_token or not access_token:
        return HttpResponse(f"Token error: {token_data}", status=400)

    okta_domain = os.getenv("OKTA_DOMAIN")
    if not okta_domain:
        raise Exception("Missing OKTA_DOMAIN environment variable")

    # Decode and verify the token
    jwks_url = f"{okta_domain}keys/"
    jwks = requests.get(jwks_url).json()
    unverified_header = jwt.get_unverified_header(id_token)

    key = next(k for k in jwks["keys"] if k["kid"] == unverified_header["kid"])

    claims = jwt.decode(
        id_token,
        key,
        algorithms=["RS256"],
        audience=os.getenv("OKTA_CLIENT_ID"),
        issuer=f"https://morsco.okta.com/oauth2/default",
        access_token=access_token
    )
    logger.debug(f"Okta Claims {claims}")

    # Extract workdayUsername and email
    workday_username = claims.get("workdayUsername")
    workday_email = claims.get("email")
    logger.debug(f"workday_username: {workday_username}")
    logger.debug(f"Session dict: {dict(request.session.items())}")

    if not workday_username:
        logger.warning("workdayUsername not found in Okta claims")

    # Create or get the user
    User = get_user_model()
    user, _ = User.objects.get_or_create(email=claims["email"], defaults={
        "username": claims["email"].split("@")[0]
    })

    # Store tokens in the session like Django OIDC
    request.session['oidc_id_token'] = id_token
    request.session['oidc_access_token'] = access_token
    request.session['oidc_token_data'] = token_data  # optional: store full token response
    request.session['workday_username'] = workday_username
    request.session['workday_email'] = workday_email
    request.session.modified = True

    login(request, user)

     # Go to the route in prodbranch_setting_management/urls.py that is named branch_settings_list
    if user and user.is_active:
        # return redirect(reverse("prodbranch_setting_management:branch_settings_list"))
        return redirect("home")
    else:
        logger.debug(f"OKTA BAD")
        return redirect("some_login_error_page")


@login_required
def branch_manual_settings_eclipse_view(request):


@login_required
def branch_manual_settings_view(request):
    """
    Display a summary view of manual setting statistics per branch.
    Redirects single-branch users directly to their branch edit page.
    """
    # If a user is not a super-user (admin) and their
    # branch security only gives them access to a single branch
    # then we skip the "multi-branch" view -
    # The just go into their branch's dashboard
    if not request.user.is_superuser:
        branch_accesses = UserBranchAccess.objects.filter(user=request.user)
        if branch_accesses.count() == 1:
            branch = branch_accesses.first().branch
            return redirect(f"/manual_settings/stock-settings/{branch.pk}/")

    # Aggregate manual setting data for all branches
    branches_data = (
        ProdBranch.objects.select_related(
            "branch",
            "branch_size",
            "branch_size_manual_setting_limit",
            "branch_manual_setting_limit",
        )
        .values("branch")
        .annotate(
            division=F("branch__division"),
            region=F("branch__region__name"),
            branch_id_name=Concat(F("branch"), Value(" - "), F("branch__branch_name")),
            stock_products=Count("id", filter=Q(stock_flag_binary=True)),
            # Manuel setting are setting that have their minimum inventory
            # quantity overriden manually.
            manual_settings_count=Count("id", filter=Q(manual_minimum__gt=0)),
            # The manuel cost is the cost of the manuel setting above the
            # system calculated settings, these are calculated at the time of
            # saving the data to make pulling back the table
            # more efficient.
            manual_cost=Sum(
                Coalesce(
                    F("change_requests__calculated_manual_cost"),
                    F("calculated_manual_cost"),
                ),
            ),
            # The effective limit is the limit on the number of
            # manual settings that a branch can have,
            # defined by either the branch size OR set explicitly
            # on the branch
            effective_limit=Coalesce(
                F("branch__branch_size__size_limit__default_manual_limit"),
                F("branch__branchmanualsettinglimit__manual_limit"),
            ),
        )
    )

    context = {"branches": branches_data}
    return render(
        request,
        "prodbranch_setting_management/branch_settings_list.html",
        context,
    )


@login_required
def stock_settings_base(request, branch):
    """
    Render the base stock settings page for a given branch.
    (This is the template that holds the structure of the page)
    """
    branch = Branch.objects.get(branch=branch)
    return render(
        request,
        "prodbranch_setting_management/stock_settings_base.html",
        context={"branch": branch},
    )


@login_required
def stock_settings_stats(request, branch):
    """
    Load branch-level stats for stock and manual settings as a partial.
    This is the table that is loaded into the "base" webpage
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
        .values("branch", "branch__branch_name")
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
            # Counting manual settings, settings where minimum/maximum
            # are greater than 0
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
            # The manuel cost is calculated when saving manual settings,
            # This is pulling it either from the raw ERP Data or
            # the "change request" data, which is in-route to the ERP...
            manual_cost=Sum(
                Coalesce(
                    F("change_requests__calculated_manual_cost"),
                    F("calculated_manual_cost"),
                    Value(0, output_field=FloatField()),
                ),
            ),
            # The efective limit is defined as the total # of manual settings
            # that a branch is able to implement, either based on
            # the size of the branch or explicitly set for the given branch
            effective_limit=Coalesce(
                F("branch__branch_size__size_limit__default_manual_limit"),
                F("branch__branchmanualsettinglimit__manual_limit"),
                Value(0, output_field=IntegerField()),
            ),
        )
    )

    context = {"stats": stats_data}
    return render(
        request,
        "prodbranch_setting_management/partials/stock_settings_stats.html",
        context,
    )


@login_required
def calculate_manual_settings_cost(request, prod_branch_id):
    """
    Calculate the projected cost of manual settings using input min/max.
    Called via HTMX to dynamically display cost before saving.
    """
    if request.method == "POST":
        prod_branch = get_object_or_404(ProdBranch, id=prod_branch_id)
        try:
            manual_minimum = int(
                request.POST.get("manual_minimum_change", "manual_minimum", 0),
            )
        except (TypeError, ValueError):
            manual_minimum = 0

        try:
            manual_maximum = int(
                request.POST.get("manual_minimum_change", "manual_maximum", 0),
            )
        except (TypeError, ValueError):
            manual_maximum = 0

        # The "cost" of the manuel settings is calculated based on the
        # inventory quantity amount manually set on top of the
        # system calculated inventory quantities
        # e.g. system "min" of two but manual min of 6 is 4
        # added in from the manual setting, the cost is from the 4 added...
        cost = 0
        if manual_minimum > prod_branch.order_point:
            cost = (manual_minimum - prod_branch.order_point) * prod_branch.average_cost
        if manual_maximum > prod_branch.line_point:
            cost = max(
                (manual_maximum - prod_branch.line_point) * prod_branch.average_cost,
                cost,
            )

        return render(
            request,
            "prodbranch_setting_management/partials/manual_settings_cost.html",
            {"cost": cost},
        )

    return JsonResponse({"error": "Invalid request"}, status=400)


@login_required
def stock_settings_edit(request, prod_branch_id):
    """
    Handle editing of a ProdBranch instance:
    - GET loads the form
    - POST saves form values as a ProdBranchChange
    """
    prod_branch = get_object_or_404(ProdBranch, id=prod_branch_id)

    # This is based on the front-end modal form, not the
    # in-line form inputs...
    if request.method == "POST":
        form = ProdBranchEditForm(request.POST, instance=prod_branch)
        if form.is_valid():
            prod_branch = form.save(commit=False)

            prod_branch_change, created = ProdBranchChange.objects.get_or_create(
                prodbranch=prod_branch,
            )

            # Attach audit data, used to create log of changes...
            prod_branch_change._changed_by = request.user  # noqa: SLF001
            prod_branch_change._change_session_id = uuid.uuid4()  # noqa: SLF001

            prod_branch_change.manual_minimum_change = form.cleaned_data[
                "manual_minimum"
            ]
            prod_branch_change.manual_maximum_change = form.cleaned_data[
                "manual_maximum"
            ]
            prod_branch_change.save()

            messages.success(request, "Settings saved successfully!")
            return redirect(
                "prodbranch_setting_management:stock_settings",
                branch=prod_branch.branch.pk,
            )
    else:
        form = ProdBranchEditForm(instance=prod_branch)

    return render(
        request,
        "prodbranch_setting_management/partials/stock_settings_edit.html",
        {
            "form": form,
            "prod_branch": prod_branch,
        },
    )


@login_required
def search_prod_branch_form(request, branch):
    """
    Display product search form if the manual setting limit hasn't been exceeded.
    Redirects to the delete confirmation if over the limit.
    """
    stats_data = get_branch_manual_limit_stats(branch)
    manual_settings = stats_data["manual_settings_count"]
    manual_limit = stats_data["effective_limit"]

    # If a branch is already above their "manual setting" limit,
    # we're not giving them the product search input to add more,
    # just a warning that they're already above their limit
    if manual_settings >= manual_limit:
        messages.warning(request, "Already at or above manual setting limit!")
        return redirect(
            "prodbranch_setting_management:manual_limit_delete",
            branch=branch,
        )

    return render(
        request,
        "prodbranch_setting_management/partials/product_selection.html",
        {"branch": branch},
    )


@login_required
def search_prod_branch_options(request, branch):
    """
    Return product search results based on a query and branch.
    Used for the product selection dropdown.
    """
    query = request.GET.get("product_search", "").strip()
    if not query:
        return HttpResponse("")

    queryset = ProdBranch.objects.filter(branch_id=branch)

    results = (
        apply_product_search_filter(queryset, query)
        .select_related("product")
        .order_by("-sales_qty_90", "-monthly_demand")[:10]
    )

    return render(
        request,
        "prodbranch_setting_management/partials/product_options.html",
        {"results": results},
    )


@login_required
def search_line_options(request, line_type, branch):
    """
    Return a list of buy line or price line values matching a search term.
    Used in advanced filter dropdowns.
    """

    # The buy line and price line filters use this same function
    # to prevent repetitive code... If searching in the buyline
    # input, but line options are returned, otherwise
    # price line otions are returned...
    query = ""
    if line_type == "buy_line":
        query = request.GET.get("buy_line_filter", "").strip()
    elif line_type == "price_line":
        query = request.GET.get("price_line_filter", "").strip()

    if not query:
        return HttpResponse("")

    search_branch = get_object_or_404(Branch, pk=branch)
    queryset = Product.objects.all()
    queryset = search_products_by_line_filter(queryset, query, line_type)

    results = queryset[:10]

    return render(
        request,
        "prodbranch_setting_management/partials/product_line_options.html",
        {"results": results, "line_type": line_type, "branch": search_branch},
    )


@login_required
def manual_limit_delete(request, branch):
    """
    Render warning panel when a branch exceeds its manual settings limit.
    """
    # This isn't to actually delete a setting
    # but is actually a warning that settings need
    # to be deleted, naming could be improved...
    stats_data = get_branch_manual_limit_stats(branch)
    manual_settings = stats_data["manual_settings_count"]
    manual_limit = stats_data["effective_limit"]

    return render(
        request,
        "prodbranch_setting_management/partials/manual_limit_delete.html",
        {
            "manual_settings": manual_settings,
            "manual_limit": manual_limit,
        },
    )


@login_required
def sales_chart_view(request, product, branch):
    """
    Render a sales chart for the given product and branch.
    Used in row-level popups or side panels.
    """
    chart = generate_sales_chart(product, branch)
    return render(
        request,
        "prodbranch_setting_management/partials/sales_chart.html",
        {"chart": chart},
    )


@login_required
def update_prodbranch_change(request, prodbranch_id):
    """
    Save inline edits to a ProdBranchChange and return updated row HTML.
    Also supports toggling the keep_manual_settings_flag from the form.
    """
    prodbranch = get_object_or_404(ProdBranch, pk=prodbranch_id)

    try:
        orderpoint_model_change = OrderPointModelReview.objects.get(
            prodbranch=prodbranch_id,
        )
    except ObjectDoesNotExist:
        orderpoint_model_change = None
    # Keep manual setting flag was introduced
    # for a specific event during the initializion of the
    # pilot project, could potentially be pulled out
    # to simplify code...
    if "keep_manual_settings_flag" not in request.POST:
        prodbranch_change, _ = ProdBranchChange.objects.get_or_create(
            prodbranch=prodbranch,
        )
        for stock_field in [
            "manual_minimum_change",
            "manual_maximum_change",
            "stockflag_change",
        ]:
            if stock_field in request.POST:
                setattr(
                    prodbranch_change,
                    stock_field,
                    int(request.POST.get(stock_field))
                    if stock_field != "stockflag_change"
                    else request.POST.get(stock_field) == "on",
                )
        for buy_pack_field in [
            "buy_pack_change",
            "buy_pack_divisibility_change",
        ]:
            if buy_pack_field in request.POST:
                setattr(
                    prodbranch_change,
                    buy_pack_field,
                    int(request.POST.get(buy_pack_field))
                    if buy_pack_field != "buy_pack_divisibility_change"
                    else request.POST.get(buy_pack_field) == "on"
                )
        prodbranch_change.save()

    if "keep_manual_settings_flag" in request.POST and orderpoint_model_change:
        orderpoint_model_change.keep_manual_settings_flag = (
            request.POST.get("keep_manual_settings_flag") == "on"
        )
        orderpoint_model_change.save()

    # Reload and return updated row
    annotated_page = get_paginated_prodbranches(
        request,
        ProdBranch.objects.filter(id=prodbranch.id),
        per_page=1,
        page_number=1,
    )
    # After the save is done, the updated record is returned
    # so the changes are immediately shown in the dashboard
    if annotated_page.object_list:
        review_filter = request.POST.get("review_filter", "")
        manual_setting_review_filter = (
            review_filter == ProdBranchReviewFilters.MANUAL_SETTING_REVIEW.value
        )
        prodbranch_data = annotated_page.object_list[0]
        context = build_prodbranch_context(prodbranch_data)
        context["manual_setting_review_filter"] = manual_setting_review_filter

        return render(
            request,
            "prodbranch_setting_management/partials/_formset_row.html",
            context,
        )

    return HttpResponse(status=404)


@login_required
def edit_prod_branches(request, branch):
    """
    Render page structure and filter controls for editing stock settings.
    Initial table rows are loaded via HTMX after page load.
    """
    # This is for the structure of the dashboard page,
    # Just returned the structure template...
    branch = get_object_or_404(Branch, pk=branch)
    context = {
        "branch": branch,
        "prodbranch_review_filters": ProdBranchReviewFilters,
        "prodbranch_sorting": ProdBranchSorting,
    }

    return render(
        request,
        "prodbranch_setting_management/partials/edit_prod_branches.html",
        context,
    )


@login_required
def load_formset_rows(request, branch):
    """
    Load paginated rows of ProdBranch forms for display.
    Filters and pagination are applied based on the request.
    """
    # This is the code that loads in the table rows of data,
    # this is seperate from the "structure" load
    # so the page structure loads immediately,
    # while the data is loading...
    branch = get_object_or_404(Branch, pk=branch)
    try:
        page_number = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page_number = 1

    prodbranch_queryset = ProdBranch.objects.filter(branch=branch)
    prodbranch_queryset = filter_prodbranches(request, prodbranch_queryset)

    page_obj = get_paginated_prodbranches(request, prodbranch_queryset, page_number)
    formset_data = [build_prodbranch_context(pb) for pb in page_obj.object_list]

    context = {
        "formset_data": formset_data,
        "branch": branch,
        "manual_setting_review_filter": request.GET.get("review_filter", "")
        == ProdBranchReviewFilters.MANUAL_SETTING_REVIEW.value,
    }

    return render(
        request,
        "prodbranch_setting_management/partials/_formset_rows.html",
        context,
    )


@login_required
def load_pagination_controls(request, branch):
    """
    Load pagination control partial for ProdBranch rows.
    """
    # This is intentionally seperately loaded from the
    # table rows being loaded in, even though much of the
    # logic is the same... The utility/helper functions
    # are used to keep the app dry, the sepereate processing
    # is to load the elements based on different front-end triggers...
    branch = get_object_or_404(Branch, pk=branch)
    try:
        page_number = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page_number = 1

    prodbranch_queryset = ProdBranch.objects.filter(branch=branch)
    prodbranch_queryset = filter_prodbranches(request, prodbranch_queryset)

    page_obj = get_paginated_prodbranches(request, prodbranch_queryset, page_number)

    context = {
        "page_obj": page_obj,
        "paginator": page_obj.paginator,
        "branch": branch,
        "previous_page": max(page_obj.number - 1, 1),
        "next_page": min(page_obj.number + 1, page_obj.paginator.num_pages),
    }

    return render(
        request,
        "prodbranch_setting_management/partials/_pagination_controls.html",
        context,
    )


@login_required
def load_applied_filters(request):
    """
    Render applied filters panel for the stock settings view.
    """
    # This renders a list of badges above the table for
    # every applied filter, just giving visibility
    # to the filtering that they applied...
    applied_filters = build_applied_filters(request)
    return render(
        request,
        "prodbranch_setting_management/partials/_applied_filters.html",
        {"applied_filters": applied_filters},
    )


@login_required
def regional_metrics(request):
    """
    Generate and render regional-level compliance and stocking metrics.
    Combines RSL targets and actual stocking data across branches.
    """

    # This renders the table of the regional stock list view that
    # shows the regional metrics...
    prodbranch_qs = ProdBranch.objects.all()
    region_metrics = (
        prodbranch_qs.values(
            "branch__region__pk",
            "branch__region__name",
            "branch__region__slug",
        )
        .annotate(
            num_branches=Count("branch", distinct=True),
            stocked_items=Count("id", filter=Q(stock_flag_binary=True)),
            avg_stocked_items=ExpressionWrapper(
                Count("id", filter=Q(stock_flag_binary=True))
                * 1.0
                / Count("branch", distinct=True),
                output_field=FloatField(),
            ),
        )
        .order_by("branch__region__name")
    )

    rsl_total_map = {
        item["region_id"]: item["rsl_items"]
        for item in RegionProductStockingList.objects.values("region_id").annotate(
            rsl_items=Count("id"),
        )
    }

    rsl_stocked_map = {
        item["region_id"]: item["rsl_stocked_items"]
        for item in RegionProductStockingList.objects.filter(
            product__prodbranch__stock_flag_binary=True,
            product__prodbranch__branch__region=F("region"),
        )
        .values("region_id")
        .annotate(rsl_stocked_items=Count("id"))
    }

    # Calculating the metrics seperately, then rejoining them
    # was done to make the overall queries more efficient
    # and performant - having the joing occur by the
    # ORM created query wasn't effecient nor fast enough...

    results = []
    for row in region_metrics:
        region_pk = row["branch__region__pk"]
        total_rsl = rsl_total_map.get(region_pk, 0)
        stocked_rsl = rsl_stocked_map.get(region_pk, 0)
        num_branches = row["num_branches"]

        row["rsl_items"] = total_rsl
        row["avg_rsl_items"] = (stocked_rsl / num_branches) if num_branches else 0
        row["compliancy"] = row["avg_rsl_items"] / total_rsl if total_rsl else 0.0
        results.append(row)

    return render(
        request,
        "prodbranch_setting_management/regional_aggregated_metrics.html",
        {"region_metrics": results},
    )


@login_required
def region_branches_stocking_product(request, region_slug, product_id):
    """
    Display a row for each branch in a region showing if it's stocking a given product.
    """

    # This logic just shows the branches that are stocking the
    # "RSL" product within the selected region,
    # just a quick view to see non-compliance...
    region = get_object_or_404(Region, slug=region_slug)
    product = get_object_or_404(Product, pk=product_id)
    branches = Branch.objects.filter(region=region).order_by("branch")
    existing_prodbranches = ProdBranch.objects.filter(
        branch__in=branches,
        product=product,
    )
    prodbranch_dict = {pb.branch.branch: pb for pb in existing_prodbranches}

    final_branch_list = []
    for branch in branches:
        prodbranch = prodbranch_dict.get(branch.branch)
        if not prodbranch:
            prodbranch = ProdBranch(
                branch=branch,
                product=product,
                stock_flag_binary=False,
            )
        final_branch_list.append(prodbranch)

    return render(
        request,
        "prodbranch_setting_management/partials/region_branches_stocking_product.html",
        {
            "product": product,
            "prodbranches": final_branch_list,
        },
    )


@login_required
def regional_stock_list_base(request, region_slug):
    """
    Render base container for regional stock list dashboard.
    """
    # This is just loading the structure of the page for
    # the "RSL" product view, when drilling into a region...
    region = get_object_or_404(Region, slug=region_slug)
    return render(
        request,
        "prodbranch_setting_management/regional_stock_list_base.html",
        {"region": region},
    )


@login_required
def edit_regional_stock_list(request, region_slug):
    """
    Render regional stock list edit view with compliance metrics.
    """
    # Again, the naming of the function could be a bit clearer...
    # This is loading the overall top-line metrics for the page
    region = get_object_or_404(Region, slug=region_slug)

    rsl_lookup = {
        r.product_id: r.initial_stock_quantity
        for r in RegionProductStockingList.objects.filter(region=region)
    }

    prodbranch_qs = ProdBranch.objects.filter(branch__region=region)
    num_branches = prodbranch_qs.values("branch").distinct().count()
    stocked_items = prodbranch_qs.filter(stock_flag_binary=True).count()
    rsl_stocked_items = prodbranch_qs.filter(
        stock_flag_binary=True,
        product_id__in=rsl_lookup.keys(),
    ).count()
    num_rsl_items = RegionProductStockingList.objects.filter(region=region).count()

    avg_stocked = stocked_items / num_branches if num_branches else 0
    avg_rsl_stocked = rsl_stocked_items / num_branches if num_branches else 0
    avg_rsl = num_rsl_items / num_branches if num_branches else 0
    # Compliancy is measured based the number of branches in the region
    # stocking the "RSL" product divided by the total number of
    # branches in the region...
    compliancy = (avg_rsl_stocked / num_rsl_items) if avg_rsl else 0

    overall_metrics = {
        "num_branches": num_branches,
        "stocked_items": stocked_items,
        "rsl_stocked_items": rsl_stocked_items,
        "avg_stocked": avg_stocked,
        "avg_rsl_stocked": avg_rsl_stocked,
        "num_rsl_items": num_rsl_items,
        "avg_rsl": avg_rsl,
        "compliancy_percent": compliancy,
    }

    return render(
        request,
        "prodbranch_setting_management/partials/edit_regional_stock_list.html",
        {
            "region": region,
            "overall_metrics": overall_metrics,
        },
    )


@login_required
def load_regional_stock_list_rows(request, region_slug):
    """
    Load paginated product rows for the regional stock list view.
    """
    # This just loads in the table rows for the "RSL" page...
    region = get_object_or_404(Region, slug=region_slug)
    prodbranch_queryset = ProdBranch.objects.filter(branch__region=region)

    try:
        page_number = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page_number = 1

    page_obj = get_paginated_regional_stock_list(
        prodbranch_queryset,
        region,
        page_number,
    )

    return render(
        request,
        "prodbranch_setting_management/partials/_regional_stock_list_rows.html",
        {
            "region": region,
            "product_data": page_obj,
        },
    )


@login_required
def load_regional_pagination_controls(request, region_slug):
    """
    Render pagination controls for regional stock list view.
    """
    # This loads in the pagination navigation controls,
    # loaded in seperately so triggers can update
    # the table rows and pagination controls seperately
    region = get_object_or_404(Region, slug=region_slug)
    prodbranch_queryset = ProdBranch.objects.filter(branch__region=region)

    try:
        page_number = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page_number = 1

    page_obj = get_paginated_regional_stock_list(
        prodbranch_queryset,
        region,
        page_number,
    )

    return render(
        request,
        "prodbranch_setting_management/partials/_regional_pagination_controls.html",
        {
            "region": region,
            "page_obj": page_obj,
            "paginator": page_obj.paginator,
            "previous_page": max(page_obj.number - 1, 1),
            "next_page": min(page_obj.number + 1, page_obj.paginator.num_pages),
        },
    )


@login_required
def update_regional_stock_list(request, region_slug, product_id):
    """
    Save updates to a region's stock list flag or quantity for a product.
    Reload the updated row from the first page of results.
    """
    region = get_object_or_404(Region, slug=region_slug)

    record, created = RegionProductStockingList.objects.get_or_create(
        region=region,
        product_id=product_id,
    )

    # When someone turns on a RSL product, we're also saving the
    # quantity, but if they turn off the RSL product,
    # we're immediatly removing the RSL Initial Quantity...
    rsl_flag = request.POST.get("rsl_flag") in ["on", "true"]
    try:
        rsl_initial = int(request.POST.get("rsl_initial", 0))
    except (ValueError, TypeError):
        rsl_initial = 0

    if not rsl_flag:
        record.delete()
    else:
        record.initial_stock_quantity = rsl_initial
        record.save()

    # After updating the data, we re-pull the information
    # from the database to send back to the front-end
    # and immediately display the new data
    prodbranch_queryset = ProdBranch.objects.filter(
        branch__region=region,
        product__product=product_id,
    )

    page_obj = get_paginated_regional_stock_list(
        prodbranch_queryset,
        region,
        page_number=1,
    )

    try:
        # used the same utility function, which is a
        # paginated queryset, so just pulling out the
        # first item...
        updated_product = page_obj.object_list[0]
    except IndexError:
        return HttpResponse(status=404)

    return render(
        request,
        "prodbranch_setting_management/partials/_regional_stock_list_row.html",
        {
            "region": region,
            "product": updated_product,
        },
    )
