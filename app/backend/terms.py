"""Everyday words -> one service key, in memory (no SQL, no LLM).

Used by the search box, the chat keyword fallback and /api/recommend. The vocabulary is the service groups
(src/06_ref_service_groups.sql: group labels and terms) plus every service's key, label and aliases.
The longest whole-word match wins, so "heart surgery" beats "heart" and "premature baby" beats "baby".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .schema import Service, ServiceGroup


@dataclass(frozen=True)
class Match:
    term: str
    group: Optional[str]      # group key
    service: Optional[str]    # specific service key, or None when only the group is known


@dataclass(frozen=True)
class Resolution:
    service: Optional[str]            # the service to search, or None
    group: Optional[ServiceGroup]     # the group it came from, when a group was involved
    used_default: bool = False        # True when the user named only the group and its default was used
    ask: Optional[str] = None         # follow-up question when a service could not be picked


_cache: dict = {}


def _index(services: list[Service], groups: list[ServiceGroup]) -> list[tuple[re.Pattern, Match]]:
    key = (id(services), id(groups), len(services), len(groups))
    if _cache.get("key") == key:
        return _cache["index"]
    group_of = {}
    for g in groups:
        for s in g.services:
            group_of.setdefault(s, g.key)
    entries: dict[str, Match] = {}

    def add(term: str, group: Optional[str], service: Optional[str], strong: bool = False):
        t = " ".join(term.lower().split())
        if len(t) < 2:
            return
        # a specific (service) entry beats a group-only entry for the same words
        if strong or t not in entries or (service and not entries[t].service):
            entries[t] = Match(t, group, service)

    for s in services:
        for t in (s.key.replace("_", " "), s.label, *s.aliases):
            add(t, group_of.get(s.key), s.key)
    for g in groups:
        add(g.label, g.key, None)
        add(g.key, g.key, None)
        for t in g.terms:
            add(t.term, g.key, t.service, strong=True)
    index = sorted(((re.compile(rf"(?<![\w-]){re.escape(t)}(?![\w-])"), m) for t, m in entries.items()),
                   key=lambda e: -len(e[1].term))
    _cache.update(key=key, index=index)
    return index


def match(text: str, services: list[Service], groups: list[ServiceGroup]) -> Optional[Match]:
    """Longest vocabulary term found in `text` as whole words, or None."""
    t = " ".join((text or "").lower().replace("’", "'").split())
    if not t:
        return None
    for rx, m in _index(services, groups):
        if rx.search(t):
            return m
    return None


def match_turns(texts: list[str], services: list[Service], groups: list[ServiceGroup]) -> Optional[Match]:
    """Match a conversation, newest text first. A specific service in the newest message wins; a group-only match is
    upgraded with a service from an older turn of the same group ("I need a scan" ... "MRI")."""
    group_only = None
    for text in texts:
        m = match(text, services, groups)
        if not m:
            continue
        if m.service and (group_only is None or m.group == group_only.group):
            return m
        if group_only is None and not m.service:
            group_only = m
    return group_only


def by_key(groups: list[ServiceGroup], key: Optional[str]) -> Optional[ServiceGroup]:
    return next((g for g in groups if g.key == key), None) if key else None


def _ask(g: ServiceGroup, services: list[Service]) -> str:
    labels = {s.key: s.label for s in services}
    opts = [labels.get(k, k) for k in g.services]
    q = g.refine_question or f"Which kind of {g.label.lower()} do you need?"
    return f"{q} ({' or '.join(opts)})" if len(opts) > 1 else q


def resolve(service: Optional[str], group: Optional[str], services: list[Service], groups: list[ServiceGroup]) -> Resolution:
    """Turn a (service, group) pair from the parser into the one service to search."""
    keys = {s.key for s in services}
    g = by_key(groups, group)
    if service in keys:
        if g is None or service not in g.services:
            g = next((x for x in groups if service in x.services), None)
        return Resolution(service, g)
    if g is None:
        return Resolution(None, None)
    if g.default_service in keys:
        return Resolution(g.default_service, g, used_default=len(g.services) > 1)
    return Resolution(None, g, ask=_ask(g, services))


def resolve_text(value: str, services: list[Service], groups: list[ServiceGroup]) -> Resolution:
    """A service key, label, alias, group key or everyday words -> one service (or a follow-up question)."""
    v = (value or "").strip().lower()
    for s in services:
        if v in (s.key, s.label.lower(), *[a.lower() for a in s.aliases]):
            return resolve(s.key, None, services, groups)
    g = by_key(groups, v) or next((x for x in groups if x.label.lower() == v), None)
    if g:
        return resolve(None, g.key, services, groups)
    m = match(v, services, groups)
    return resolve(m.service, m.group, services, groups) if m else Resolution(None, None)


def default_note(res: Resolution, services: list[Service]) -> Optional[str]:
    """When a group default was used, name the other options so the user can narrow it down."""
    if not (res.used_default and res.group):
        return None
    labels = {s.key: s.label for s in services}
    others = [labels.get(k, k) for k in res.group.services if k != res.service]
    if not others:
        return None
    return (f"Showing {labels.get(res.service, res.service)} for {res.group.label.lower()}. "
            f"If you need {' or '.join(others)} specifically, say so.")
