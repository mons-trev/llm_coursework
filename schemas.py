"""Runtime contracts. These do not import the benchmark or its answer labels."""
import json
import math
import re

from jsonschema import Draft202012Validator


def object_schema(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


STRINGS = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
NUMBER = {"type": ["number", "null"], "minimum": 0}
RANGE = object_schema({"min": NUMBER, "max": NUMBER})
PLAN_SCHEMA = {
    "type": "object", "minProperties": 1,
    "patternProperties": {
        r"^day[1-9][0-9]*_[a-z][a-z0-9]*$": {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "pattern": r"^F[0-9]{3}$"},
        }
    },
    "additionalProperties": False,
}
CONSTRAINT_SCHEMA = object_schema({
    "plan": object_schema({
        "days": {"type": "integer", "minimum": 1},
        "meals_per_day": {**STRINGS, "minItems": 1,
                          "items": {"type": "string", "pattern": r"^[a-z][a-z0-9]*$"}},
    }),
    "constraints": object_schema({
        "budget_krw": object_schema({"total_max": NUMBER, "per_meal_max": NUMBER}),
        "nutrition": object_schema({
            "per_meal": object_schema({"energy_kcal": RANGE, "protein_g": RANGE}),
            "per_day": object_schema({"sodium_mg": RANGE}),
        }),
        "excluded_allergens": STRINGS,
        "excluded_food_codes": STRINGS,
        "cuisine_types": {"anyOf": [STRINGS, {"type": "null"}]},
        "excluded_cuisine_types": STRINGS,
        "required_tags": STRINGS,
        "excluded_tags": STRINGS,
    }),
})
VERDICT_SCHEMA = object_schema({"passed": {"type": "boolean"},
                                "feedback": {"type": "string"}})


def validate(value, schema):
    # Python's JSON parser otherwise accepts non-finite numbers.
    def finite(v):
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("numbers must be finite")
        if isinstance(v, dict):
            for child in v.values():
                finite(child)
        elif isinstance(v, list):
            for child in v:
                finite(child)
    finite(value)
    error = next(Draft202012Validator(schema).iter_errors(value), None)
    if error:
        path = ".".join(map(str, error.absolute_path)) or "root"
        raise ValueError(f"{path}: {error.message}")


def validate_constraints(value):
    validate(value, CONSTRAINT_SCHEMA)
    nutrition = value["constraints"]["nutrition"]
    for group in nutrition.values():
        for bounds in group.values():
            lo, hi = bounds["min"], bounds["max"]
            if lo is not None and hi is not None and lo > hi:
                raise ValueError("nutrition minimum exceeds maximum")


def extract_json(text):
    blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return json.loads(blocks[-1] if blocks else text)


def extract_plan(text):
    value = extract_json(text) if isinstance(text, str) else text
    plan = value.get("plan", value) if isinstance(value, dict) else value
    validate(plan, PLAN_SCHEMA)
    return plan
