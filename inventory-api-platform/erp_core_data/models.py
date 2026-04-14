from django.db import models
from django.utils.text import slugify

from .managers import BranchAccessManager


class BranchSize(models.Model):
    """
    Represents the size classification of a branch
    (e.g., small, medium, large).
    """

    size_description = models.CharField(max_length=20)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.id} - {self.size_description}"


class Region(models.Model):
    """
    Defines a geographic or organizational region
    with a unique slug for URL use.
    """

    id = models.CharField(
        primary_key=True,
        max_length=10,
        unique=True,
        db_index=True,
    )
    name = models.CharField(
        max_length=256,
        unique=True,
        db_index=True,
    )
    last_updated = models.DateTimeField(auto_now=True)
    slug = models.SlugField(unique=True, blank=True)

    # Custom manager to filter region access based on branch permissions
    objects = BranchAccessManager(branch_lookup="branches__branch")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Auto-generate slug from name if not provided
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Branch(models.Model):
    """
    Represents a physical or operational branch with
    geographic and administrative details.
    """

    branch = models.CharField(primary_key=True, max_length=4, db_index=True)
    branch_name = models.CharField(max_length=256, blank=True)
    branch_size = models.ForeignKey(
        BranchSize,
        on_delete=models.SET_NULL,
        null=True,
        db_index=True,
    )
    division = models.CharField(max_length=256, blank=True)
    region = models.ForeignKey(
        Region,
        verbose_name="regions",
        related_name="branches",
        on_delete=models.SET_NULL,
        null=True,
    )
    full_address = models.CharField(max_length=256, blank=True)
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
    )
    last_updated = models.DateTimeField(auto_now=True)

    # Custom manager for branch-level access control
    objects = BranchAccessManager(branch_lookup="branch")

    class Meta:
        ordering = ["branch"]

    def __str__(self):
        return f"{self.branch} - {self.branch_name}"


class BuyLine(models.Model):
    """
    Defines a buy line, categorizing products
    under purchasing rules or vendors.
    """

    buy_line = models.CharField(primary_key=True, max_length=8, db_index=True)
    buy_line_name = models.CharField(max_length=256, blank=True, db_index=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["buy_line"]

    def __str__(self) -> str:
        return f"{self.buy_line} - {self.buy_line_name}"


class PriceLine(models.Model):
    """
    Defines a price line, grouping products
    under pricing strategies.
    """

    price_line = models.CharField(primary_key=True, max_length=8, db_index=True)
    price_line_name = models.CharField(max_length=256, blank=True, db_index=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["price_line"]

    def __str__(self) -> str:
        return f"{self.price_line} - {self.price_line_name}"


class Product(models.Model):
    """
    Represents a product with related marketing,
    categorization, and pricing details.
    """

    product = models.PositiveIntegerField(primary_key=True, db_index=True)
    product_desc = models.CharField(max_length=500, blank=True)
    vendor_model = models.CharField(max_length=50, blank=True)
    vap_flag = models.BooleanField(default=False)
    buy_line = models.ForeignKey(
        BuyLine,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="products",
        db_index=True,
    )
    price_line = models.ForeignKey(
        PriceLine,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="products",
        db_index=True,
    )
    search_key_words = models.CharField(max_length=1000, blank=True)
    image_url = models.URLField(max_length=2000, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["product"]

    def __str__(self):
        return f"{self.product} - {self.product_desc}"


class ProdBranch(models.Model):
    """
    Associates a product with a specific branch,
    tracking inventory, sales, and stocking rules.
    """

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, db_index=True)
    stock_flag_binary = models.BooleanField(db_index=True)
    last_stock_flag_change_date = models.DateField()
    rank = models.CharField(max_length=1)
    purchasing_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_DEFAULT,
        default=None,
        null=True,
        related_name="purchasing_branches",
    )
    average_cost = models.FloatField()
    monthly_demand = models.FloatField()
    sales_qty_30 = models.IntegerField()
    sales_qty_90 = models.IntegerField()
    order_point = models.IntegerField()
    line_point = models.IntegerField()
    manual_minimum = models.IntegerField(blank=True, null=True, db_index=True)
    last_manual_minimum_change_date = models.DateField()
    manual_maximum = models.IntegerField(blank=True, null=True, db_index=True)
    last_manual_maximum_change_date = models.DateField()
    calculated_manual_cost = models.FloatField(default=0, db_index=True)
    buy_pack_qty = models.IntegerField(db_index=True)
    buy_pack_divisibility_flag = models.BooleanField(db_index=True)
    last_updated = models.DateTimeField(auto_now=True)

    # Custom manager scoped to branch access
    objects = BranchAccessManager(branch_lookup="branch__branch")

    class Meta:
        constraints = [
            # Enforce unique association between a branch and product
            models.UniqueConstraint(
                fields=["branch", "product"],
                name="unique_prodbranch",
            ),
        ]

    def __str__(self):
        return f"{self.branch} - {self.product}"

    def save(self, *args, **kwargs):
        # Calculate cost of manual override only when it's greater than order point
        if self.manual_minimum is not None and self.manual_minimum > self.order_point:
            self.calculated_manual_cost = (
                self.manual_minimum - self.order_point
            ) * self.average_cost
        else:
            self.calculated_manual_cost = 0
        super().save(*args, **kwargs)


class YearMonth(models.Model):
    """
    Tracks a specific month and year, including its index relative
    to the current period.
    """

    year = models.IntegerField(db_index=True)
    month = models.IntegerField(db_index=True)
    time_index = models.IntegerField(
        default=0,
        db_index=True,
    )  # 0 for current month, -1 for last, +1 for next
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("year", "month")

    def __str__(self):
        return f"{self.year}-{self.month:02d}"


class Sales(models.Model):
    """Stores product sales quantities per branch and month."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, db_index=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, db_index=True)
    year_month = models.ForeignKey(YearMonth, on_delete=models.CASCADE, db_index=True)
    quantity = models.IntegerField()
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("branch", "product", "year_month")

    def __str__(self):
        return f"""
            Sales of {self.product} at {self.branch}
            for {self.year_month}: {self.quantity}
        """
