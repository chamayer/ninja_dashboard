"""Forms for the operator UI."""

from __future__ import annotations

from django import forms

from .models import ClientPolicy


# BLUEPRINT-defined categories. Not enforced at the model level (category is
# a free CharField) but pre-populated for consistency.
POLICY_CATEGORY_CHOICES = (
    ("", "— pick a category —"),
    ("RMM", "RMM"),
    ("AV_EDR", "AV / EDR"),
    ("Remote_Access", "Remote access"),
    ("Backup", "Backup"),
    ("VPN", "VPN"),
)


class ClientPolicyForm(forms.ModelForm):
    """Add / edit a ClientPolicy. Serializes approved_products via textarea (one per line)."""

    category = forms.ChoiceField(
        choices=POLICY_CATEGORY_CHOICES,
        help_text="Free-form; use one of the standard names for consistency with reports.",
    )
    approved_products_raw = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 8}),
        required=False,
        label="Approved products",
        help_text="One product name per line. Blank lines and leading/trailing whitespace ignored.",
    )
    agent_sla_days = forms.IntegerField(
        min_value=0,
        max_value=365,
        required=False,
        label="Agent SLA (days)",
        help_text="Optional. Days without a check-in before a device is considered non-compliant.",
    )

    class Meta:
        model = ClientPolicy
        fields = ("category",)  # Manage approved_products + agent_sla_days manually.

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["approved_products_raw"].initial = "\n".join(
                self.instance.approved_products or []
            )
            self.fields["agent_sla_days"].initial = self.instance.agent_sla_days

    def clean_approved_products_raw(self) -> list[str]:
        raw = self.cleaned_data.get("approved_products_raw", "")
        products = [line.strip() for line in raw.splitlines() if line.strip()]
        # De-dup preserving order.
        seen = set()
        result: list[str] = []
        for p in products:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def save(self, commit: bool = True) -> ClientPolicy:
        instance = super().save(commit=False)
        instance.approved_products = self.cleaned_data.get("approved_products_raw", [])
        instance.agent_sla_days = self.cleaned_data.get("agent_sla_days")
        if commit:
            instance.save()
        return instance
