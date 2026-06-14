"""
Yad2 Scraper
Fetches rental listings from Yad2's internal JSON API.
No browser needed — pure HTTP requests.
API endpoint: https://gw.yad2.co.il/realestate-feed/rent/map
"""

import logging
import hashlib
import time
import requests
from typing import Optional
from seen_store import is_seen, mark_seen
from config_store import get_cities, get_neighborhoods, get_filter

log = logging.getLogger(__name__)

BASE_URL = 'https://gw.yad2.co.il/realestate-feed/rent/map'
AUTOCOMPLETE_URL = 'https://gw.yad2.co.il/address-autocomplete/autocomplete'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Language': 'he-IL,he;q=0.9,en;q=0.8',
    'Referer': 'https://www.yad2.co.il/',
    'Origin': 'https://www.yad2.co.il',
}


def resolve_city_id(city_name: str) -> Optional[str]:
    """Resolve a Hebrew city name to a Yad2 numeric city ID via autocomplete API."""
    try:
        resp = requests.get(
            AUTOCOMPLETE_URL,
            params={'term': city_name, 'docTypes': 'cities'},
            headers=HEADERS,
            timeout=10
        )
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        for item in items:
            if item.get('type') == 'city':
                city_id = str(item.get('id', ''))
                log.info(f'Resolved city "{city_name}" → ID {city_id}')
                return city_id
        log.warning(f'Could not resolve city ID for "{city_name}"')
        return None
    except Exception as e:
        log.error(f'City ID resolution error: {e}')
        return None


def resolve_area_id(city_id: str, neighborhood_name: str) -> Optional[str]:
    """Resolve a neighborhood name to a Yad2 area ID."""
    try:
        resp = requests.get(
            AUTOCOMPLETE_URL,
            params={'term': neighborhood_name, 'docTypes': 'neighborhoods', 'cityId': city_id},
            headers=HEADERS,
            timeout=10
        )
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        for item in items:
            if item.get('type') == 'neighborhood':
                area_id = str(item.get('id', ''))
                log.info(f'Resolved neighborhood "{neighborhood_name}" → area ID {area_id}')
                return area_id
        log.warning(f'Could not resolve area ID for "{neighborhood_name}"')
        return None
    except Exception as e:
        log.error(f'Area ID resolution error: {e}')
        return None


def make_listing_id(listing: dict) -> str:
    """Stable unique ID for a Yad2 listing."""
    raw = f"yad2_{listing.get('id', '')}_{listing.get('link_token', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


def fetch_listings(city_id: str, area_id: str = None,
                   min_rooms: float = 4, max_price: int = None) -> list:
    """Fetch raw listings from Yad2 API for one city/area combination."""
    params = {
        'city': city_id,
        'minRooms': min_rooms,
    }
    if area_id:
        params['area'] = area_id
    if max_price:
        params['maxPrice'] = max_price

    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning(f'Yad2 API returned {resp.status_code} for city {city_id}')
            return []
        data = resp.json()
        markers = data.get('data', {}).get('markers', [])
        log.info(f'Yad2 API returned {len(markers)} listings for city {city_id} area {area_id}')
        return markers
    except Exception as e:
        log.error(f'Yad2 API fetch error: {e}')
        return []


def parse_listing(raw: dict, city_name: str) -> dict:
    """Parse a raw Yad2 marker into a normalized listing dict."""
    rooms = raw.get('rooms')
    price = raw.get('price')
    address = raw.get('address', {})
    street = address.get('street', {}).get('text', '')
    neighborhood = address.get('neighborhood', {}).get('text', '')
    listing_id = raw.get('id', '')
    token = raw.get('link_token', listing_id)

    return {
        'id':           make_listing_id(raw),
        'source':       'yad2',
        'city':         city_name,
        'neighborhood': neighborhood,
        'street':       street,
        'rooms':        float(rooms) if rooms else None,
        'price':        int(price) if price else None,
        'parking':      raw.get('parking'),
        'safe_room':    raw.get('safeRoom') or raw.get('safe_room'),
        'post_url':     f'https://www.yad2.co.il/item/{token}',
        'raw':          raw,
    }


def scrape_yad2() -> list:
    """
    Main entry point. Scrapes all configured cities and neighborhoods.
    Returns list of new matching listings not seen before.
    """
    cities = get_cities()
    if not cities:
        log.warning('No cities configured — skipping Yad2 scrape')
        return []

    rooms_min = float(get_filter('rooms_min', '4'))
    new_listings = []

    for city in cities:
        city_name = city['name']
        city_id = city.get('yad2_city_id')
        max_price = city.get('max_price')

        # Auto-resolve city ID if not stored
        if not city_id:
            log.info(f'Resolving Yad2 city ID for {city_name}...')
            city_id = resolve_city_id(city_name)
            if not city_id:
                log.warning(f'Skipping {city_name} — could not resolve city ID')
                continue
            # Save resolved ID back to config
            from config_store import add_city
            add_city(city_name, yad2_city_id=city_id, max_price=max_price)

        neighborhoods = get_neighborhoods(city_name)

        if neighborhoods:
            for nbhd in neighborhoods:
                area_id = nbhd.get('yad2_area_id')
                nbhd_name = nbhd['name']

                if not area_id:
                    log.info(f'Resolving area ID for {nbhd_name}...')
                    area_id = resolve_area_id(city_id, nbhd_name)
                    if area_id:
                        from config_store import add_neighborhood
                        add_neighborhood(city_name, nbhd_name, yad2_area_id=area_id)

                raw_listings = fetch_listings(
                    city_id, area_id=area_id,
                    min_rooms=rooms_min, max_price=max_price
                )
                for raw in raw_listings:
                    listing = parse_listing(raw, city_name)
                    if not is_seen(listing['id']):
                        mark_seen(listing['id'], source='yad2')
                        new_listings.append(listing)
                time.sleep(1)
        else:
            # No neighborhood filter — scrape whole city
            raw_listings = fetch_listings(
                city_id, min_rooms=rooms_min, max_price=max_price
            )
            for raw in raw_listings:
                listing = parse_listing(raw, city_name)
                if not is_seen(listing['id']):
                    mark_seen(listing['id'], source='yad2')
                    new_listings.append(listing)

    log.info(f'Yad2: {len(new_listings)} new listings')
    return new_listings
