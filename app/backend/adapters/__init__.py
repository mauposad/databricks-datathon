from functools import lru_cache

from .. import config
from .base import Adapter
from .find_care import FindCareAdapter

REGISTRY: dict[str, type[Adapter]] = {
    FindCareAdapter.name: FindCareAdapter,
}


@lru_cache(maxsize=1)
def get_adapter() -> Adapter:
    try:
        return REGISTRY[config.ADAPTER]()
    except KeyError:
        raise RuntimeError(f"Unknown ADAPTER={config.ADAPTER!r}; options: {sorted(REGISTRY)}")
