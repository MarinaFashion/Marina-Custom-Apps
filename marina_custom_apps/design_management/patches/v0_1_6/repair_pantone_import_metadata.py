"""Versioned post-model-sync fix for existing Marina Pantone installations."""

from marina_custom_apps.design_management.setup.pantone_metadata import repair_pantone_import_metadata


def execute():
    repair_pantone_import_metadata()
