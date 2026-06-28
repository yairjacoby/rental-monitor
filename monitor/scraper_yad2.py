"""
Yad2 Scraper
Fetches rental listings from Yad2's internal JSON API.
No browser needed — pure HTTP requests.
API endpoint: https://gw.yad2.co.il/realestate-feed/rent/map
"""

import logging
import hashlib
import json
import re
import time
import datetime
import zoneinfo
from curl_cffi import requests
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
    raw = f"yad2_{listing.get('orderId', '')}_{listing.get('token', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


def fetch_listings(city_id: str, region_id: str, area_id: str = None,
                   min_rooms: float = 4, max_price: int = None) -> list:
    """Fetch raw listings from Yad2 API for one city/area combination."""
    params = {
        'region': region_id,
        'city': city_id,
        'minRooms': min_rooms,
    }
    if area_id:
        params['area'] = area_id
    if max_price:
        params['maxPrice'] = max_price

    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS,
                            impersonate='chrome124', timeout=15)
        log.info(f'Yad2 response: status={resp.status_code}, length={len(resp.content)}, preview={resp.text[:300]}')
        if resp.status_code != 200:
            log.warning(f'Yad2 API returned {resp.status_code} for city {city_id}')
            return []
        if not resp.content:
            log.warning(f'Yad2 API returned empty body for city {city_id} — possible IP block')
            return []
        data = resp.json()
        markers = data.get('data', {}).get('markers', [])
        log.info(f'Yad2 API returned {len(markers)} listings for city {city_id} area {area_id}')
        return markers
    except Exception as e:
        log.error(f'Yad2 API fetch error: {e}')
        return []


_CONDITION_MAP = {1: 'חדש', 2: 'במצב טוב', 3: 'דורש שיפוץ'}


def parse_listing(raw: dict, city_name: str) -> dict:
    """Parse a raw Yad2 marker into a normalized listing dict."""
    details = raw.get('additionalDetails', {})
    rooms = details.get('roomsCount')
    price = raw.get('price')
    address = raw.get('address', {})
    street = address.get('street', {}).get('text', '')
    neighborhood = address.get('neighborhood', {}).get('text', '')
    house = address.get('house', {})
    token = raw.get('token', str(raw.get('orderId', '')))

    meta = raw.get('metaData', {})
    image_urls = list(meta.get('images', []))
    if not image_urls and meta.get('coverImage'):
        image_urls = [meta['coverImage']]

    return {
        'id':           make_listing_id(raw),
        'source':       'yad2',
        'city':         city_name,
        'neighborhood': neighborhood,
        'street':       street,
        'rooms':        float(rooms) if rooms else None,
        'price':        int(price) if price else None,
        'sqm':          details.get('squareMeter'),
        'floor':        house.get('floor'),
        'condition':    _CONDITION_MAP.get(details.get('propertyCondition', {}).get('id')),
        'parking':      None,
        'safe_room':    None,
        'balcony':      None,
        'elevator':     None,
        'ac':           None,
        'storage':      None,
        'furnished':    None,
        'boiler':       None,
        'token':        token,
        'post_url':     f'https://www.yad2.co.il/item/{token}',
        'image_urls':   image_urls,
        'detected_at':  datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Jerusalem')).strftime('%H:%M'),
        'raw':          raw,
    }


def fetch_listing_detail(token: str) -> dict:
    """Fetch full amenity data from the Yad2 listing page using Playwright (bypasses Radware)."""
    try:
        from playwright.sync_api import sync_playwright
        try:
            from playwright_stealth import stealth_sync as _stealth_sync
        except ImportError:
            _stealth_sync = None
        log.info(f'Playwright: loading {token}')
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled',
                      '--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/124.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1280, 'height': 800},
                locale='he-IL',
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            if _stealth_sync:
                _stealth_sync(page)
            page.goto(f'https://www.yad2.co.il/item/{token}',
                      wait_until='domcontentloaded', timeout=20000)
            log.info(f'Playwright: page loaded for {token} — title={page.title()!r}')
            page.wait_for_selector('#__NEXT_DATA__', timeout=12000)
            log.info(f'Playwright: found __NEXT_DATA__ for {token}')
            raw_json = page.locator('#__NEXT_DATA__').inner_text()
            browser.close()
        data = json.loads(raw_json)
        queries = (data.get('props', {}).get('pageProps', {})
                   .get('dehydratedState', {}).get('queries', []))
        if not queries:
            log.warning(f'Playwright: no queries in __NEXT_DATA__ for {token}')
            return {}
        in_prop = queries[0].get('state', {}).get('data', {}).get('inProperty', {})
        log.info(f'Detail {token}: {in_prop}')
        return {
            'parking':   in_prop.get('includeParking'),
            'safe_room': in_prop.get('includeBuildingShelter'),
            'balcony':   in_prop.get('includeBalcony'),
            'elevator':  in_prop.get('includeElevator'),
            'ac':        in_prop.get('includeAirConditioning'),
            'storage':   in_prop.get('includeStorage'),
            'furnished': in_prop.get('includeFurnished'),
            'boiler':    in_prop.get('includeBoiler'),
        }
    except Exception as e:
        log.warning(f'fetch_listing_detail failed for {token}: {e}')
        return {}


def scrape_yad2() -> tuple:
    """
    Main entry point. Scrapes all configured cities and neighborhoods.
    Returns (new_listings, cities_with_no_results).
    """
    cities = get_cities()
    if not cities:
        log.warning('No cities configured — skipping Yad2 scrape')
        return [], []

    rooms_min = float(get_filter('rooms_min', '4'))
    require_parking   = get_filter('must_have_parking',  'false') == 'true'
    require_safe_room = get_filter('must_have_safe_room', 'false') == 'true'
    MAX_DETAIL_FETCHES = 10
    detail_fetches = 0
    new_listings = []
    cities_with_no_results = []

    for city in cities:
        city_name = city['name']
        city_id = city.get('yad2_city_id')
        region_id = city.get('yad2_region_id')
        max_price = city.get('max_price')

        if not city_id or not region_id:
            log.warning(f'Skipping {city_name} — yad2_city_id or yad2_region_id not set')
            continue

        neighborhoods = get_neighborhoods(city_name)

        # Always use area 54 for city-level search, filter by neighborhood post-fetch
        area_id = neighborhoods[0].get('yad2_area_id') if neighborhoods else None
        nbhd_names = [n['name'].lower().replace('שכונה ', '').replace('מתחם ', '').strip()
                     for n in neighborhoods] if neighborhoods else []

        raw_listings = fetch_listings(
            city_id, region_id, area_id=area_id,
            min_rooms=rooms_min, max_price=max_price
        )

        new_listings_this_city = []

        for raw in raw_listings:
            listing = parse_listing(raw, city_name)

            # Strict neighborhood filter — skip if neighborhood unknown or doesn't match
            if nbhd_names:
                listing_nbhd = listing.get('neighborhood', '').lower().strip()
                if not listing_nbhd:
                    log.info('Skipping listing — neighborhood not specified by Yad2')
                    continue
                listing_nbhd_clean = listing_nbhd.replace('שכונה ', '').replace('מתחם ', '').strip()
                if not any(n in listing_nbhd_clean or listing_nbhd_clean in n
                           for n in nbhd_names):
                    log.info(f'Skipping {listing_nbhd} — not in {nbhd_names}')
                    continue

            if not is_seen(listing['id']):
                if detail_fetches < MAX_DETAIL_FETCHES:
                    detail = fetch_listing_detail(listing['token'])
                    if detail:
                        listing.update(detail)
                        log.info(f'Detail fetched for {listing["id"][:8]}: parking={listing.get("parking")} safe_room={listing.get("safe_room")}')
                    detail_fetches += 1
                if require_parking and listing.get('parking') is False:
                    log.info(f'Skipping {listing["id"][:8]} — no parking (filter active)')
                    continue
                if require_safe_room and listing.get('safe_room') is False:
                    log.info(f'Skipping {listing["id"][:8]} — no safe room (filter active)')
                    continue
                mark_seen(listing['id'], source='yad2')
                new_listings.append(listing)
                new_listings_this_city.append(listing)

        log.info(f'{city_name}: {len(raw_listings)} raw → {len(new_listings_this_city)} new (unseen)')
        if nbhd_names and not new_listings_this_city:
            cities_with_no_results.append(city_name)

    log.info(f'Yad2: {len(new_listings)} new listings')
    return new_listings, cities_with_no_results
