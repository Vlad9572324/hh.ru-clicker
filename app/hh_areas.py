"""Cached country hierarchy from HH's public areas directory."""

import threading
import time

import requests


_URL = "https://api.hh.ru/areas"
_TTL_SECONDS = 24 * 60 * 60
_LOCK = threading.Lock()
_CACHE = {"expires": 0.0, "countries": [], "country_by_area": {}}


def _walk(node, country_id, mapping):
    node_id = str(node.get("id") or "")
    if node_id:
        mapping[node_id] = country_id
    for child in node.get("areas") or []:
        if isinstance(child, dict):
            _walk(child, country_id, mapping)


def area_directory():
    """Return HH countries and a descendant-area to country-ID lookup."""
    now = time.monotonic()
    with _LOCK:
        if _CACHE["countries"] and _CACHE["expires"] > now:
            return _CACHE["countries"], _CACHE["country_by_area"]
        response = requests.get(_URL, headers={"User-Agent": "hh-clicker"}, timeout=15)
        response.raise_for_status()
        roots = response.json()
        if not isinstance(roots, list):
            raise ValueError("HH areas response is not a list")
        countries, mapping = [], {}
        for root in roots:
            if not isinstance(root, dict) or not root.get("id") or not root.get("name"):
                continue
            country_id = str(root["id"])
            countries.append({"id": country_id, "name": str(root["name"])})
            _walk(root, country_id, mapping)
        countries.sort(key=lambda item: item["name"].casefold())
        _CACHE.update(expires=now + _TTL_SECONDS, countries=countries, country_by_area=mapping)
        return countries, mapping


def country_for_area(area_id):
    """Resolve a city/region ID returned by a vacancy to its HH country ID."""
    if not area_id:
        return ""
    _, mapping = area_directory()
    return mapping.get(str(area_id), "")
