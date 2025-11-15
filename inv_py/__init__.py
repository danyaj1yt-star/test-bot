"""inv_py package: re-export internal modules for easier imports.

This package exposes the modules moved into the inv_py package so other
modules can import them as `inv_py.shop`, `inv_py.render_inventory`, etc.
Keeping simple explicit relative imports helps static analyzers and avoids
runtime import shenanigans.
"""

from . import shop
from . import inventory
from . import render_inventory
from . import config_inventory
from . import shop_config

__all__ = [
    'shop', 'inventory', 'render_inventory', 'config_inventory', 'shop_config'
]
