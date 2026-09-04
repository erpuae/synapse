# Copyright (c) 2026, Dxbitz and contributors
"""Seed the Synapse Component catalog. Idempotent, safe to re-run on every migrate."""

from synapse.components.catalog import seed


def execute():
	seed()
