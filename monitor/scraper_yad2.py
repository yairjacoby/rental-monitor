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
from seen_store import is_seen, mark_seen, get_seen_set
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


_CONDITION_MAP = {
    1: 'חדש מקבלן',
    2: 'משופץ',
    3: 'במצב שמור',
    4: 'במצב טוב',
    5: 'דורש שיפוץ',
    6: 'חדש (גרו בנכס)',
}


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

    # Try to get amenities directly from the map API marker (gw.yad2.co.il — no Radware)
    in_prop_raw = raw.get('inProperty') or {}
    amenities = _parse_in_property(in_prop_raw)

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
        'parking':      amenities.get('parking'),
        'safe_room':    amenities.get('safe_room'),
        'balcony':      amenities.get('balcony'),
        'elevator':     amenities.get('elevator'),
        'ac':           amenities.get('ac'),
        'storage':      amenities.get('storage'),
        'furnished':    amenities.get('furnished'),
        'boiler':       amenities.get('boiler'),
        'token':        token,
        'post_url':     f'https://www.yad2.co.il/item/{token}',
        'image_urls':   image_urls,
        'detected_at':  datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Jerusalem')).strftime('%H:%M'),
        'raw':          raw,
    }


def _parse_in_property(in_prop: dict) -> dict:
    """Map Yad2 inProperty fields to our listing keys."""
    def _bool(val):
        if val is None:
            return None
        return bool(val)
    return {
        'parking':   _bool(in_prop.get('includeParking')),
        'safe_room': _bool(in_prop.get('includeSecurityRoom')),
        'balcony':   _bool(in_prop.get('includeBalcony')),
        'elevator':  _bool(in_prop.get('includeElevator')),
        'ac':        _bool(in_prop.get('includeAirconditioner')),
        'storage':   _bool(in_prop.get('includeWarehouse')),
        'furnished': _bool(in_prop.get('includeFurnished')),
        'boiler':    _bool(in_prop.get('includeBoiler')),
    }


def _extract_in_property_from_html(html: str, token: str) -> dict:
    """Pull inProperty out of __NEXT_DATA__ embedded in HTML."""
    if '__NEXT_DATA__' not in html:
        return {}
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.DOTALL
    )
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        queries = (data.get('props', {}).get('pageProps', {})
                   .get('dehydratedState', {}).get('queries', []))
        if not queries:
            return {}
        item_data = queries[0].get('state', {}).get('data', {})
        in_prop = item_data.get('inProperty', {})
        result = _parse_in_property(in_prop)
        # Use condition text from detail page (more accurate than map API ID-only)
        cond_text = (item_data.get('additionalDetails', {})
                     .get('propertyCondition', {}).get('text'))
        if cond_text:
            result['condition'] = cond_text
        log.info(f'Detail {token}: {result}')
        return result
    except Exception as e:
        log.warning(f'__NEXT_DATA__ parse error for {token}: {e}')
        return {}


def fetch_listing_detail(token: str) -> dict:
    """Fetch amenity + description data for a listing.
    Attempt 1: curl_cffi (fast, works on residential IPs)
    Attempt 2: ScraperAPI residential proxy (bypasses Railway datacenter IP block)
    Attempt 3: Playwright stealth (last resort)
    """
    import os, urllib.parse
    url = f'https://www.yad2.co.il/item/{token}'

    # ── Attempt 1: curl_cffi (works on non-datacenter IPs, e.g. local dev) ──────
    try:
        resp = requests.get(url, headers={**HEADERS, 'Accept': 'text/html'}, impersonate='chrome124', timeout=12)
        result = _extract_in_property_from_html(resp.text, token)
        if result:
            log.info(f'Detail {token}: fetched via curl_cffi')
            return result
    except Exception as e:
        log.debug(f'Detail {token}: curl_cffi failed ({e})')

    # ── Attempt 2: ScraperAPI residential proxy (bypasses Radware on Railway) ───
    scraperapi_key = os.environ.get('SCRAPERAPI_KEY')
    if scraperapi_key:
        try:
            proxy_url = (f'https://api.scraperapi.com/?api_key={scraperapi_key}'
                         f'&url={urllib.parse.quote(url, safe="")}')
            resp = requests.get(proxy_url, impersonate='chrome124', timeout=30)
            result = _extract_in_property_from_html(resp.text, token)
            if result:
                log.info(f'Detail {token}: fetched via ScraperAPI')
                return result
            log.warning(f'Detail {token}: ScraperAPI returned no __NEXT_DATA__')
        except Exception as e:
            log.warning(f'Detail {token}: ScraperAPI failed ({e})')
    else:
        log.info(f'Detail {token}: SCRAPERAPI_KEY not set — skipping proxy attempt')

    # ── Attempt 3: Playwright with stealth ───────────────────────────────────────
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
            page.goto(url, wait_until='domcontentloaded', timeout=20000)
            log.info(f'Playwright: page loaded for {token} — title={page.title()!r}')
            page.wait_for_selector('#__NEXT_DATA__', timeout=12000)
            raw_json = page.locator('#__NEXT_DATA__').inner_text()
            browser.close()

        data = json.loads(raw_json)
        queries = (data.get('props', {}).get('pageProps', {})
                   .get('dehydratedState', {}).get('queries', []))
        if not queries:
            log.warning(f'Playwright: no queries in __NEXT_DATA__ for {token}')
            return {}
        in_prop = queries[0].get('state', {}).get('data', {}).get('inProperty', {})
        log.info(f'Detail {token} via Playwright: {in_prop}')
        return _parse_in_property(in_prop)
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

        # City-level fetch (no area_id) — filter by neighborhood name post-fetch.
        # Using a single neighborhood's area_id when multiple are configured would
        # silently exclude listings in the other neighbourhoods.
        nbhd_names = [n['name'].lower().replace('שכונה ', '').replace('מתחם ', '').strip()
                     for n in neighborhoods] if neighborhoods else []

        raw_listings = fetch_listings(
            city_id, region_id,
            min_rooms=rooms_min, max_price=max_price
        )

        # Pass 1: parse all raw markers and apply neighbourhood filter
        matched_listings = []
        in_prop_present = 0
        for raw in raw_listings:
            listing = parse_listing(raw, city_name)
            if raw.get('inProperty'):
                in_prop_present += 1

            if nbhd_names:
                listing_nbhd = listing.get('neighborhood', '').lower().strip()
                if not listing_nbhd:
                    continue
                listing_nbhd_clean = listing_nbhd.replace('שכונה ', '').replace('מתחם ', '').strip()
                if not any(n in listing_nbhd_clean or listing_nbhd_clean in n
                           for n in nbhd_names):
                    continue

            matched_listings.append(listing)

        log.info(f'{city_name}: {len(raw_listings)} raw ({in_prop_present} with inProperty) → {len(matched_listings)} neighbourhood-matched')

        # Pass 2: batch seen-check, then fetch details only for new listings
        seen_ids = get_seen_set([l['id'] for l in matched_listings])
        new_listings_this_city = []

        for listing in matched_listings:
            if listing['id'] in seen_ids:
                continue

            amenities_from_map = any(
                listing.get(k) is not None
                for k in ('parking', 'safe_room', 'balcony', 'elevator', 'ac')
            )
            if not amenities_from_map and detail_fetches < MAX_DETAIL_FETCHES:
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

        log.info(f'{city_name}: {len(new_listings_this_city)} new (unseen)')
        # Only suggest expanding when the neighbourhood filter blocks everything — not
        # when listings exist but are all already seen (which is normal operation).
        if nbhd_names and raw_listings and not matched_listings:
            cities_with_no_results.append(city_name)

    log.info(f'Yad2: {len(new_listings)} new listings')
    return new_listings, cities_with_no_results
