"""Validate the manifest that each feature sends in its hello message."""
from __future__ import annotations

from typing import Any

from . import ContractError
from .records import FEATURE
from .settings import validate_schema
from .templates import validate_template


def validate_manifest(manifest: Any) -> dict[str, Any]:
    """Return the manifest with its templates keyed by ID.

    Each template ID must start with the feature name, so two features cannot
    replace each other's templates.
    """
    if not isinstance(manifest, dict) or set(manifest) != {"feature", "title", "version", "settings", "templates"}:
        raise ContractError("manifest must have exactly feature, title, version, settings, and templates")
    feature = manifest["feature"]
    if not isinstance(feature, str) or not FEATURE.match(feature):
        raise ContractError(f"feature name {feature!r} is invalid")
    for name in ("title", "version"):
        if not isinstance(manifest[name], str) or not 1 <= len(manifest[name]) <= 64:
            raise ContractError(f"manifest {name} must be 1 to 64 characters")
    validate_schema(manifest["settings"])
    if not isinstance(manifest["templates"], list) or not manifest["templates"]:
        raise ContractError("manifest needs at least one template")
    templates = {}
    for template in manifest["templates"]:
        validate_template(template)
        if not template["id"].startswith(feature + "."):
            raise ContractError(f"template {template['id']} must start with {feature}.")
        if template["id"] in templates:
            raise ContractError(f"template {template['id']} is listed twice")
        templates[template["id"]] = template
    return {**manifest, "templates": templates}
