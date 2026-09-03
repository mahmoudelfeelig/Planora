"""Sealed package marker for the isolated MUNI-FSPSX solver.

The official runner imports only the explicitly captured ITC-2019 modules.
Keeping this package initializer empty avoids executing the workspace-wide
benchmark registry and its unrelated transitive imports.
"""
