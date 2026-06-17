from dataclasses import dataclass

from .by_name import locate_by_name as _locate_by_name


@dataclass(frozen=True)
class Location:
    country: str | None
    city: str | None


def locate_by_name(name, country_res=None, city_res=None):
    country, city = _locate_by_name(name, country_res, city_res)
    return Location(country=country, city=city)


def region_label(name, country_res=None, city_res=None):
    """Human-readable recognized region for a node name: "JP/Tokyo", "US", or
    "?" when nothing matches. Pure — for listing/display, independent of which
    countries the user opted into city-level grouping for."""
    loc = locate_by_name(name, country_res, city_res)
    if not loc.country:
        return "?"
    return f"{loc.country}/{loc.city}" if loc.city else loc.country
