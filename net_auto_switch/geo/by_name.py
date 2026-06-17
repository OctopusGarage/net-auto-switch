"""Pure name -> Location matcher. Cities first (more specific), then countries."""

from . import catalog


def locate_by_name(name, country_res=None, city_res=None):
    country_res = catalog.COUNTRY_RES if country_res is None else country_res
    city_res = catalog.CITY_RES if city_res is None else city_res
    for city, (country, rx) in city_res.items():
        if rx.search(name):
            return country, city
    for country, rx in country_res.items():
        if rx.search(name):
            return country, None
    return None, None
