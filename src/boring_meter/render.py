"""Plain-text rendering. No color, no animation, readable at 72 columns."""

from __future__ import annotations

import textwrap
from typing import List

WIDTH = 72


def heading(title: str) -> List[str]:
    return [title, "-" * min(len(title), WIDTH)]


def banner(subtitle: str) -> List[str]:
    return ["BORING METER", subtitle, ""]


def kv(label: str, value: str, width: int = 22) -> List[str]:
    first = "%-*s %s" % (width, label + ":", value)
    if len(first) <= WIDTH:
        return [first]
    wrapped = textwrap.wrap(value, WIDTH - width - 1) or [""]
    return ["%-*s %s" % (width, label + ":", wrapped[0])] + [" " * (width + 1) + w for w in wrapped[1:]]


def para(text: str, indent: int = 0) -> List[str]:
    prefix = " " * indent
    return textwrap.wrap(text, WIDTH, initial_indent=prefix, subsequent_indent=prefix) or [""]


def bullet(text: str, indent: int = 2) -> List[str]:
    return textwrap.wrap(text, WIDTH, initial_indent=" " * indent + "- ", subsequent_indent=" " * (indent + 2)) or [""]


def num(n) -> str:
    return "{:,}".format(n)


def token_value(entry: dict) -> str:
    """Render a category total without ever presenting unknown data as zero."""
    if entry["known"] == 0:
        return "unknown (not recorded)" if entry["missing"] else "no data"
    text = num(entry["sum"])
    if entry["missing"]:
        text += " (%s request(s) missing this value)" % num(entry["missing"])
    return text


def money(amount: str, currency: str) -> str:
    symbol = "$" if currency == "USD" else ""
    return "%s%s %s" % (symbol, amount, currency)
