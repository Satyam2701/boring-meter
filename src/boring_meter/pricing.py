"""API list-price cost estimation with explicit assumptions.

A record is priced only when every token category is known and every pricing
modifier on the record is modeled. Anything else stays unpriced with a reason.
Unknown models are never priced with another model's rates. Aliases are an explicit
table in pricing.json (dated snapshot IDs only).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Tuple

from boring_meter.errors import BMError
from boring_meter.paths import display_path

BUNDLED = Path(__file__).with_name("pricing.json")
MILLION = Decimal(1000000)
CATEGORIES = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")
STANDARD_GEO = {None, "", "global", "not_available"}
STANDARD_SPEED = {None, "", "standard"}
STANDARD_TIER = {None, "", "standard"}

ASSUMPTIONS = [
    "Prices are Anthropic first-party Claude API list prices (see pricing_version). They are not what a Claude Pro, Max, Team or Enterprise subscription charges.",
    "Excludes Batch API discounts, Priority Tier, server-side tool fees such as web search, taxes, credits, and negotiated discounts.",
    "Requests on Amazon Bedrock or Google Cloud have separate partner pricing that is not modeled.",
    "Records with inference_geo missing, 'global' or 'not_available', and speed missing, are priced at standard global rates.",
]


def _dec(value, where: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BMError("INVALID_PRICING", "Invalid price %r at %s." % (value, where))
    if result < 0:
        raise BMError("INVALID_PRICING", "Negative price at %s." % where)
    return result


def _validate(data: dict, source: str) -> dict:
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise BMError("INVALID_PRICING", "%s is not a version 1 Boring Meter pricing file." % source)
    for key in ("pricing_version", "effective_date", "currency", "unit"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise BMError("INVALID_PRICING", "%s is missing '%s'." % (source, key))
    models = data.get("models")
    if not isinstance(models, dict) or not models:
        raise BMError("INVALID_PRICING", "%s has no models." % source)
    parsed = {}
    for name, spec in models.items():
        if not isinstance(spec, dict):
            raise BMError("INVALID_PRICING", "%s: model %s must be an object." % (source, name))
        entry = {c: _dec(spec.get(c), "%s.%s" % (name, c)) for c in CATEGORIES}
        if "inference_geo_us_multiplier" in spec:
            entry["geo_us"] = _dec(spec["inference_geo_us_multiplier"], name + ".inference_geo_us_multiplier")
        if "fast" in spec:
            entry["fast"] = {c: _dec(spec["fast"].get(c), "%s.fast.%s" % (name, c)) for c in ("input", "output")}
        if "long_context" in spec:
            lc = spec["long_context"]
            entry["long_context"] = {c: _dec(lc.get(c), "%s.long_context.%s" % (name, c)) for c in CATEGORIES}
            threshold = lc.get("threshold_prompt_tokens")
            if not isinstance(threshold, int) or threshold <= 0:
                raise BMError("INVALID_PRICING", "%s: %s.long_context needs threshold_prompt_tokens." % (source, name))
            entry["long_context"]["threshold"] = threshold
        parsed[name] = entry
    aliases = data.get("aliases", {})
    if not isinstance(aliases, dict) or any(v not in parsed for v in aliases.values()):
        raise BMError("INVALID_PRICING", "%s has an alias that points to an unknown model." % source)
    return {
        "pricing_version": data["pricing_version"],
        "effective_date": data["effective_date"],
        "retrieved_from": data.get("retrieved_from"),
        "currency": data["currency"],
        "unit": data["unit"],
        "notes": data.get("notes", []),
        "models": parsed,
        "aliases": dict(aliases),
        "source": source,
    }


def load_pricing(cfg: dict) -> Optional[dict]:
    """Load the bundled pricing table or the user's pricing.file. None when disabled."""
    if not cfg.get("pricing.enabled", True):
        return None
    custom = cfg.get("pricing.file", "")
    path = Path(custom).expanduser() if custom else BUNDLED
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise BMError("INVALID_PRICING", "Pricing file %s was not found." % display_path(path), "Fix or clear pricing.file in settings.")
    except (OSError, ValueError) as exc:
        raise BMError("INVALID_PRICING", "Pricing file %s could not be read (%s)." % (display_path(path), exc.__class__.__name__))
    return _validate(data, "bundled pricing table" if not custom else display_path(path))


def resolve_model(model: Optional[str], pricing: dict) -> Optional[str]:
    if not model:
        return None
    if model in pricing["models"]:
        return model
    return pricing["aliases"].get(model)


def price_record(record: dict, pricing: dict) -> Tuple[Optional[Decimal], Optional[str]]:
    """Return (cost, None) or (None, reason). Cost is in pricing['currency']."""
    if record.get("synthetic"):
        return None, "synthetic placeholder message (not an API request)"
    model = resolve_model(record.get("model"), pricing)
    if model is None:
        return None, "no price for model %s" % (record.get("model") or "(missing)")
    values = {k: record.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens")}
    if any(v is None for v in values.values()):
        return None, "missing token category"
    if record.get("service_tier") not in STANDARD_TIER:
        return None, "service tier %s not modeled" % record.get("service_tier")
    speed = record.get("speed")
    if speed not in STANDARD_SPEED and speed != "fast":
        return None, "speed %s not modeled" % speed
    geo = record.get("inference_geo")
    if geo not in STANDARD_GEO and geo != "us":
        return None, "inference_geo %s not modeled" % geo
    spec = pricing["models"][model]
    rates = {c: spec[c] for c in CATEGORIES}
    prompt_tokens = values["input_tokens"] + values["cache_read_tokens"] + values["cache_creation_tokens"]
    if "long_context" in spec and prompt_tokens > spec["long_context"]["threshold"]:
        rates = {c: spec["long_context"][c] for c in CATEGORIES}
    if speed == "fast":
        if "fast" not in spec:
            return None, "fast mode price not known for %s" % model
        read_ratio = spec["cache_read"] / spec["input"]
        fast_in = spec["fast"]["input"]
        rates = {
            "input": fast_in,
            "output": spec["fast"]["output"],
            "cache_write_5m": fast_in * Decimal("1.25"),
            "cache_write_1h": fast_in * Decimal("2"),
            "cache_read": fast_in * read_ratio,
        }
    creation = values["cache_creation_tokens"]
    other = record.get("other_token_metrics") or {}
    five, hour = other.get("cache_creation_5m"), other.get("cache_creation_1h")
    if creation == 0:
        five, hour = 0, 0
    elif five is None or hour is None or five + hour != creation:
        return None, "cache write duration (5m or 1h) unknown"
    cost = (
        values["input_tokens"] * rates["input"]
        + values["output_tokens"] * rates["output"]
        + values["cache_read_tokens"] * rates["cache_read"]
        + five * rates["cache_write_5m"]
        + hour * rates["cache_write_1h"]
    ) / MILLION
    if geo == "us":
        if "geo_us" not in spec:
            return None, "inference_geo us multiplier not known for %s" % model
        cost *= spec["geo_us"]
    return cost, None


def list_price_ratio(model_a: str, model_b: str, pricing: dict) -> Optional[Tuple[Decimal, Decimal]]:
    """Return (input ratio, output ratio) of b's list price to a's, or None."""
    a = resolve_model(model_a, pricing)
    b = resolve_model(model_b, pricing)
    if not a or not b:
        return None
    pa, pb = pricing["models"][a], pricing["models"][b]
    return pb["input"] / pa["input"], pb["output"] / pa["output"]
