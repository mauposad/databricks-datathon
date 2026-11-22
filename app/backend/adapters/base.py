"""Adapter interface: anything that can turn a Query into ranked Recommendations.

To plug in another model or cleaned dataset, subclass Adapter, return the shapes in schema.py,
and register the class in adapters/__init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..schema import Query, RecommendResponse, Service, ServiceGroup


class Adapter(ABC):
    name: str = "base"

    @abstractmethod
    def services(self) -> list[Service]:
        """Searchable services, for the dropdown and for chat parsing."""

    def service_groups(self) -> list[ServiceGroup]:
        """Optional broad care groups over the services (with everyday terms), for the picker and for chat parsing."""
        return []

    def places(self) -> list[str]:
        """Optional place suggestions (districts, cities) for autocomplete."""
        return []

    @abstractmethod
    def recommend(self, q: Query) -> RecommendResponse:
        """Top-N recommendations with evidence."""

    def prefetch(self) -> None:
        """Optional: load reference data (services, places) ahead of the first request."""
        self.services()
        self.places()

    def invalidate_results(self) -> None:
        """Optional: drop cached search results (called after a reviewer verification)."""
