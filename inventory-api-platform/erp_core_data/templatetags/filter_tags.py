from collections.abc import Callable

from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()

MAX_VALUE_WITH_DECIMAL = 10


@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs) -> str:
    """
    Return encoded URL parameters based on the current request's GET parameters,
    updating or adding any specified parameters from kwargs.

    Useful for preserving query parameters in paginated or filtered views.
    """
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        params[key] = value
    # Remove any parameters with empty values
    for key in [key for key, value in params.items() if not value]:
        del params[key]
    return params.urlencode()


def format_percent(value: float) -> str:
    """Formats a float as a percentage with no decimal places."""
    return f"{round(value * 100, 0)}%"


def format_dollars(value: float) -> str:
    """
    Formats a float as a dollar amount.
    Shows two decimals if under threshold, else rounds to nearest whole.
    """
    if value < MAX_VALUE_WITH_DECIMAL:
        return f"${intcomma(round(value, 2))}"
    return f"${intcomma(int(round(value, 0)))}"


def format_quantity(value: float) -> str:
    """
    Formats a float as a quantity with appropriate units.
    Includes one decimal if under threshold.
    """
    if value < MAX_VALUE_WITH_DECIMAL:
        return f"{intcomma(round(value, 1))} ea."
    return f"{intcomma(int(round(value, 0)))} ea."


def format_weight(value: float) -> str:
    """Formats a float as a whole-number weight in pounds."""
    return f"{intcomma(int(round(value, 0)))}lbs"


def format_load_factor(value: float) -> str:
    """Formats a float as a whole-number load factor."""
    return f"{intcomma(int(round(value, 0)))}LF"


def format_count(value: float) -> str:
    """Formats a float as a whole-number count."""
    return f"{intcomma(int(round(value, 0)))}"


def default_formatter(value: float) -> str:
    """Default formatter for values not matched by a format type."""
    return f"{intcomma(int(round(value, 0)))}"


# Mapping of format type strings to corresponding formatting functions
FORMAT_MAPPING: dict[str, Callable[[float], str]] = {
    "percent": format_percent,
    "dollars": format_dollars,
    "quantity": format_quantity,
    "weight": format_weight,
    "load_factor": format_load_factor,
    "count": format_count,
}


@register.simple_tag(takes_context=True)
def value_formatter(value: float | str, format_type: str) -> str:
    """
    Format a value using a specified formatting type.

    Args:
        value (float | str): The value to be formatted.
        format_type (str): One of the keys defined in FORMAT_MAPPING.

    Returns:
        str: A string representation of the formatted value.
    """
    if value:
        try:
            value = float(value)
        except (ValueError, TypeError):
            return "Invalid value"
    else:
        value = 0.0

    formatter = FORMAT_MAPPING.get(format_type, default_formatter)
    return formatter(value)


# Register value_formatter as both a simple_tag and a template filter
register.filter("value_formatter", value_formatter)
