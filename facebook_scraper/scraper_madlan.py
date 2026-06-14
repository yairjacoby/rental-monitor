"""
Madlan Scraper
Scrapes rental listings from Madlan using Playwright.
Listings are server-side rendered — no public API available.
URL pattern: https://www.madlan.co.il/for-rent/{city}-ישראל?filters=_{minPrice}-{maxPrice}_{minRooms}-
"""

import logging
import hashlib
import time
import random
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from seen_store import is_seen, mark_seen
from config_store import get_cities, get_neighborhoods, get_filter

log = logging.getLogger(__name__)

BASE_URL = 'https://www.madlan.co.il/for-rent'
LOGIN_WALL_SIGNALS = ['התחבר', 'הירשם', 'login', 'sign up']


def make_listing_id(url: str, price: str, address: str) -> str:
    raw = f'madlan_{url}_{price}_{address}'
    return hashlib.md5(raw.encode()).hexdigest()


def build_madlan_url(city_name: str, neighborhood_name: str = None,
                     min_rooms: float = 4, max_price: int = None) -> str:
    """Build Madlan search URL with filters encoded in path."""
    # Madlan uses Hebrew city name with dashes in URL
    city_slug = city_name.replace(' ', '-')
    if neighborhood_name:
        location = f'{neighborhood_name.replace(" ", "-")}-{city_slug}'
    else:
        location = city_slug

    min_price = 0
    price_max = max_price or 99999
    rooms_min = int(min_rooms)

    # Filter pattern: _{minPrice}-{maxPrice}_{minRooms}-____
    filters = f'_{min_price}-{price_max}_{rooms_min}-____'

    return f'{BASE_URL}/{location}-ישראל?filters={filters}&marketplace=residential'


def extract_listings_from_page(page) -> list[dict]:
    """Extract listing cards from rendered Madlan page."""
    listings = []
    try:
        # Wait for listing cards to appear
        page.wait_for_selector('[data-testid="feed-item"], .feed-item, article',
                               timeout=15000)
    except PlaywrightTimeout:
        log.warning('Timed out waiting for Madlan listing cards')
        return []

    # Try multiple possible selectors for listing cards
    selectors = [
        '[data-testid="feed-item"]',
        '.feed-list-item',
        'article[class*="listing"]',
        '[class*="FeedItem"]',
    ]

    elements = []
    for selector in selectors:
        elements = page.query_selector_all(selector)
        if elements:
            log.info(f'Found {len(elements)} Madlan cards with selector: {selector}')
            break

    if not elements:
        log.warning('No listing cards found on Madlan page')
        return []

    for el in elements:
        try:
            text = el.inner_text().strip()
            if not text or len(text) < 20:
                continue

            # Extract price
            price = None
            price_match = re.search(r'([\d,]+)\s*[₪₪]', text)
            if price_match:
                price = price_match.group(1).replace(',', '')

            # Extract rooms
            rooms = None
            rooms_match = re.search(r'(\d+\.?\d*)\s*(?:חדרים|חד)', text)
            if rooms_match:
                rooms = rooms_match.group(1)

            # Extract address
            address = ''
            address_el = el.query_selector('[class*="address"], [class*="Address"], [data-testid*="address"]')
            if address_el:
                address = address_el.inner_text().strip()

            # Extract listing URL
            post_url = ''
            link_el = el.query_selector('a[href*="/item/"], a[href*="/for-rent/"]')
            if link_el:
                href = link_el.get_attribute('href') or ''
                post_url = href if href.startswith('http') else f'https://www.madlan.co.il{href}'

            # Detect parking and safe room from text
            parking = 'חניה' in text or 'חנייה' in text
            safe_room = 'ממ"ד' in text or 'ממד' in text or 'מרחב מוגן' in text

            listing_id = make_listing_id(post_url, price or '', address)

            listings.append({
                'id':           listing_id,
                'source':       'madlan',
                'price':        int(price) if price else None,
                'rooms':        float(rooms) if rooms else None,
                'address':      address,
                'parking':      parking if parking else None,
                'safe_room':    safe_room if safe_room else None,
                'post_url':     post_url,
                'raw_text':     text[:500],
            })

        except Exception as e:
            log.debug(f'Error extracting Madlan card: {e}')
            continue

    return listings


def scrape_city(page, city_name: str, neighborhood_name: str = None,
                min_rooms: float = 4, max_price: int = None) -> list[dict]:
    """Scrape one city/neighborhood combination."""
    url = build_madlan_url(city_name, neighborhood_name, min_rooms, max_price)
    log.info(f'Scraping Madlan: {url}')

    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(random.uniform(3.0, 4.0))

        # Check for login wall
        body_text = page.inner_text('body').lower()
        if any(signal in body_text for signal in LOGIN_WALL_SIGNALS):
            log.warning(f'Possible login wall on Madlan — {url}')

        # Scroll to load more listings
        for _ in range(3):
            page.evaluate('window.scrollBy(0, window.innerHeight * 2)')
            time.sleep(random.uniform(1.5, 2.5))

        return extract_listings_from_page(page)

    except PlaywrightTimeout:
        log.warning(f'Timeout loading Madlan page: {url}')
        return []
    except Exception as e:
        log.error(f'Error scraping Madlan {url}: {e}')
        return []


def scrape_madlan() -> list[dict]:
    """
    Main entry point. Scrapes all configured cities and neighborhoods.
    Returns list of new listings not seen before.
    """
    cities = get_cities()
    if not cities:
        log.warning('No cities configured — skipping Madlan scrape')
        return []

    rooms_min = float(get_filter('rooms_min', '4'))
    new_listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = browser.new_context(
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            locale='he-IL',
            timezone_id='Asia/Jerusalem',
            viewport={'width': 1280, 'height': 900},
        )
        page = context.new_page()

        for city in cities:
            city_name = city['name']
            max_price = city.get('max_price')
            neighborhoods = get_neighborhoods(city_name)

            if neighborhoods:
                for nbhd in neighborhoods:
                    raw = scrape_city(
                        page, city_name,
                        neighborhood_name=nbhd['name'],
                        min_rooms=rooms_min,
                        max_price=max_price
                    )
                    for listing in raw:
                        if not is_seen(listing['id']):
                            mark_seen(listing['id'], source='madlan')
                            new_listings.append(listing)
                    time.sleep(random.uniform(2.0, 3.0))
            else:
                raw = scrape_city(
                    page, city_name,
                    min_rooms=rooms_min,
                    max_price=max_price
                )
                for listing in raw:
                    if not is_seen(listing['id']):
                        mark_seen(listing['id'], source='madlan')
                        new_listings.append(listing)

        browser.close()

    log.info(f'Madlan: {len(new_listings)} new listings')
    return new_listings
