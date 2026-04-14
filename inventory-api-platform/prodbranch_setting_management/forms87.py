from django import forms
from erp_core_data.models import ProdBranch


class ProdBranchEditForm(forms.ModelForm):
    """
    Form for editing key ProdBranch fields, with HTMX attributes
    for dynamic, inline updates within a table row context.
    """

    manual_minimum = forms.IntegerField(
        required=False,
        label="Manual Minimum",
        widget=forms.NumberInput(
            attrs={
                "hx-post": "",  # Set dynamically in __init__
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "closest tr",
                "hx-include": "closest form",
                "class": "form-control",
            },
        ),
    )

    manual_maximum = forms.IntegerField(
        required=False,
        label="Manual Maximum",
        widget=forms.NumberInput(
            attrs={
                "hx-post": "",
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "closest tr",
                "hx-include": "closest form",
                "class": "form-control",
            },
        ),
    )

    stock_flag = forms.BooleanField(
        required=False,
        label="Stock Flag",
        widget=forms.CheckboxInput(
            attrs={
                "hx-post": "",
                "hx-trigger": "change",
                "hx-target": "closest tr",
                "hx-include": "closest form",
            },
        ),
    )

    buy_pack_div = forms.BooleanField(
        required=False,
        label="Buy Pack Divisibility",
        widget=forms.CheckboxInput(
            attrs={
                "hx-post": "",
                "hx-trigger": "change",
                "hx-target": "closest tr",
                "hx-include": "closest form",
            },
        ),
    )

    buy_pack = forms.IntegerField(
        required=False,
        label="Buy Pack Quantity",
        widget=forms.NumberInput(
            attrs={
                "hx-post": "",
                "hx-trigger": "keyup changed delay:300ms",
                "hx-target": "closest tr",
                "hx-include": "closest form",
                "class": "form-control",
            },
        ),
    )

    keep_manual_settings_flag = forms.BooleanField(
        required=False,
        label="keep_manual_settings_flag",
        widget=forms.CheckboxInput(
            attrs={
                "hx-post": "",
                "hx-trigger": "change",
                "hx-target": "closest tr",
                "hx-include": "closest form",
            },
        ),
    )

    class Meta:
        model = ProdBranch
        fields = ["stock_flag"]

    def __init__(self, *args, **kwargs):
        """
        Dynamically inject hx-post URL into all fields based on the instance's ID.
        """
        super().__init__(*args, **kwargs)

        if self.instance:
            hx_post_url = f"/manual_settings/update-pending-change/{self.instance.pk}/"
            self.fields["manual_minimum"].widget.attrs["hx-post"] = hx_post_url
            self.fields["manual_maximum"].widget.attrs["hx-post"] = hx_post_url
            self.fields["stock_flag"].widget.attrs["hx-post"] = hx_post_url
            self.fields["buy_pack"].widget.attrs["hx-post"] = hx_post_url
            self.fields["buy_pack_div"].widget.attrs["hx-post"] = hx_post_url
            self.fields["keep_manual_settings_flag"].widget.attrs["hx-post"] = (
                hx_post_url
            )
