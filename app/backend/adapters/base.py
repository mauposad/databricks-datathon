"""Adapter interface: anything that can turn a Query into ranked Recommendations.

To plug in another model or cleaned dataset, subclass Adapter, return the shapes in schema.py,
and register the class in adapters/__init__.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..schema import Query, RecommendResponse, Service


class Adapter(ABC):
    name: str = "base"

    @abstractmethod
    def services(self) -> list[Service]:
        """Searchable services, for the dropdown and for chat parsing."""

    def places(self) -> list[str]:
        """Optional place suggestions (districts, cities) for autocomplete."""
        return []

    @abstractmethod
    def recommend(self, q: Query) -> RecommendResponse:
        """Top-N recommendations with evidence."""
