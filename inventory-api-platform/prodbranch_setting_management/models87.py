import uuid

from django.contrib.auth import get_user_model
from django.db import models
from erp_core_data.managers import BranchAccessManager


class ProdBranchChange(models.Model):
    """
    Tracks pending change requests for a ProdBranch,
    such as stock flag and manual min/max changes.
    """

    prodbranch = models.OneToOneField(
        "erp_core_data.ProdBranch",
        on_delete=models.CASCADE,
        related_name="change_requests",
        db_index=True,
    )
    stockflag_change = models.BooleanField(null=True)
    manual_minimum_change = models.IntegerField(null=True)
    manual_maximum_change = models.IntegerField(null=True)
    calculated_manual_cost = models.FloatField(default=0)
    buy_pack_change = models.IntegerField(null=True)
    buy_pack_divisibility_change = models.BooleanField(null=True)
    last_updated = models.DateTimeField(auto_now=True)

    objects = BranchAccessManager(branch_lookup="prodbranch__branch__branch")

    def __str__(self):
        return f"Change Request for {self.prodbranch}"

    def save(self, *args, **kwargs):
        # Calculate estimated manual cost if minimum exceeds order point
        if (
            self.manual_minimum_change is not None
            and self.manual_minimum_change > self.prodbranch.order_point
        ):
            self.calculated_manual_cost = (
                self.manual_minimum_change - self.prodbranch.order_point
            ) * self.prodbranch.average_cost
        elif self.manual_minimum_change is None:
            self.calculated_manual_cost = self.prodbranch.calculated_manual_cost
        else:
            self.calculated_manual_cost = 0
        super().save(*args, **kwargs)


class BranchSizeManualSettingLimit(models.Model):
    """
    Sets the default manual minimum limit based on branch size.
    """

    branch_size = models.OneToOneField(
        "erp_core_data.BranchSize",
        on_delete=models.CASCADE,
        related_name="size_limit",
    )
    default_manual_limit = models.PositiveIntegerField()
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.branch_size} - Limit: {self.default_manual_limit}"


class BranchManualSettingLimitManager(models.Manager):
    """
    Custom manager for retrieving effective manual
    setting limits for branches.
    """

    def get_effective_limits(self):
        """Get effective limits for all branches."""
        from erp_core_data.models import Branch

        return [
            {
                "branch": branch,
                "effective_limit": BranchManualSettingLimit.get_effective_limit(branch),
            }
            for branch in Branch.objects.all()
        ]


class BranchManualSettingLimit(models.Model):
    """
    Allows override of default manual setting limits at the individual branch level.
    """

    branch = models.OneToOneField("erp_core_data.Branch", on_delete=models.CASCADE)
    manual_limit = models.PositiveIntegerField(blank=True, null=True)
    last_updated = models.DateTimeField(auto_now=True)

    objects = BranchManualSettingLimitManager()

    def __str__(self):
        return f"{self.branch} - Effective Limit: {self.effective_limit}"

    @classmethod
    def get_effective_limit(cls, branch):
        """
        Returns the manual limit for a branch,
        falling back to the default for its branch size.
        """
        manual_limit = cls.objects.filter(branch=branch).first()
        if manual_limit and manual_limit.manual_limit is not None:
            return manual_limit.manual_limit
        return branch.branch_size.size_limit.default_manual_limit

    @staticmethod
    def batch_get_effective_limits(branches):
        """
        Batch calculates the effective manual setting limits
        for a list of branches.

        Args:
            branches (list): A list of Branch instances.

        Returns:
            dict: A dictionary mapping branch ID to its
            effective manual limit.
        """
        branch_ids = [branch.branch for branch in branches]

        manual_limits = BranchManualSettingLimit.objects.filter(
            branch_id__in=branch_ids,
        ).values("branch_id", "manual_limit")

        manual_limit_dict = {
            item["branch_id"]: item["manual_limit"] for item in manual_limits
        }

        branch_size_defaults = {
            branch.branch: branch.branch_size.size_limit.default_manual_limit
            for branch in branches
        }

        effective_limits = {}
        for branch in branches:
            branch_id = branch.branch
            manual_limit = manual_limit_dict.get(branch_id)
            effective_limits[branch_id] = (
                manual_limit
                if manual_limit is not None
                else branch_size_defaults.get(branch_id, 0)
            )

        return effective_limits


class ChangeLog(models.Model):
    """
    Audit log capturing changes made to ProdBranch fields.
    Changes are grouped by change_session_id to track related edits together.
    """

    prod_branch = models.ForeignKey(
        "erp_core_data.ProdBranch",
        on_delete=models.CASCADE,
        related_name="change_logs",
    )
    change_session_id = models.UUIDField(default=uuid.uuid4, editable=False)
    field_name = models.CharField(max_length=255)
    previous_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    new_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    changed_by = models.ForeignKey(
        get_user_model(),
        on_delete=models.SET_NULL,
        null=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    objects = BranchAccessManager(branch_lookup="prod_branch__branch__branch")

    def __str__(self):
        return (
            f"Change {self.change_session_id} - {self.field_name} "
            f"in {self.prod_branch} by {self.changed_by}"
        )


class RegionProductStockingList(models.Model):
    """
    Indicates which products are included on the
    stocking list for a given region.
    """

    region = models.ForeignKey(
        "erp_core_data.Region",
        on_delete=models.CASCADE,
        db_index=True,
    )
    product = models.ForeignKey(
        "erp_core_data.Product",
        on_delete=models.CASCADE,
        db_index=True,
    )
    initial_stock_quantity = models.PositiveIntegerField(null=True)
    last_updated = models.DateTimeField(auto_now=True)

    objects = BranchAccessManager(branch_lookup="region__branches__branch")

    class Meta:
        unique_together = ("region", "product")

    def __str__(self):
        return f"{self.region} - {self.product}"


class OrderPointModelReview(models.Model):
    """
    Stores AI/algorithm-suggested order point values and
    recommendations for a ProdBranch.
    """

    prodbranch = models.OneToOneField(
        "erp_core_data.ProdBranch",
        on_delete=models.CASCADE,
        related_name="order_point_model",
        db_index=True,
    )
    new_order_point_model_flag = models.BooleanField()
    new_order_point = models.PositiveIntegerField(null=True)
    suggested_manual_setting_removal_flag = models.BooleanField()
    suggested_manual_setting_removal_reason = models.CharField(
        max_length=500,
        blank=True,
    )
    keep_manual_settings_flag = models.BooleanField(default=False)

    def __str__(self):
        return f"OrderPoint Model for {self.prodbranch}"
