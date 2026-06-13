"""
Facebook Group Scraper
Scrapes public Facebook groups for rental listings using Playwright.
No login required — public groups only.
"""

import logging
import hashlib
import time
import random
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from seen_store import is_seen, mark_seen

log = logging.getLogger(__name__)

SCROLL_ROUNDS = 5          # how many times to scroll down per group
SCROLL_PAUSE = 2.0         # seconds between scrolls
POST_LIMIT = 20            # max posts to collect per group per cycle
LOGIN_WALL_SIGNALS = [
    'log in to facebook',
    'create new account',
    'you must log in',
    'sign up for facebook',
]


def make_post_id(group_url: str, post_text: str) -> str:
    """Stable unique ID from group + first 200 chars of post text."""
    raw = group_url + post_text[:200]
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def is_login_wall(page_text: str) -> bool:
    lower = page_text.lower()
    return any(signal in lower for signal in LOGIN_WALL_SIGNALS)


def scrape_group(page, group_url: str) -> list[dict]:
    """Scrape one public Facebook group. Returns list of raw post dicts."""
    posts = []
    try:
        log.info(f'Scraping group: {group_url}')
        page.goto(group_url, wait_until='domcontentloaded', timeout=30000)
        time.sleep(random.uniform(3.0, 4.0))

        page_text = page.inner_text('body')

        if is_login_wall(page_text):
            log.warning(f'Login wall detected for {group_url} — skipping')
            return []

        # Scroll to load more posts
        for i in range(SCROLL_ROUNDS):
            page.evaluate('window.scrollBy(0, window.innerHeight * 2)')
            time.sleep(random.uniform(SCROLL_PAUSE, SCROLL_PAUSE + 1.0))
            log.debug(f'Scroll {i+1}/{SCROLL_ROUNDS}')

        # Extract post elements
        # Facebook posts are in [data-ad-preview="message"] or role="article"
        post_elements = page.query_selector_all('[role="article"]')
        log.info(f'Found {len(post_elements)} post elements in {group_url}')

        for el in post_elements[:POST_LIMIT]:
            try:
                text = el.inner_text().strip()
                if len(text) < 30:
                    continue

                # Try to get post URL from any <a> containing /posts/ or /permalink/
                post_url = group_url  # fallback
                links = el.query_selector_all('a[href*="/posts/"], a[href*="/permalink/"]')
                if links:
                    href = links[0].get_attribute('href')
                    if href:
                        post_url = href if href.startswith('http') else f'https://www.facebook.com{href}'

                post_id = make_post_id(group_url, text)

                if is_seen(post_id):
                    continue

                posts.append({
                    'id':        post_id,
                    'source':    'facebook',
                    'group_url': group_url,
                    'post_url':  post_url,
                    'text':      text,
                    'scraped_at': datetime.now(timezone.utc).isoformat(),
                })
                mark_seen(post_id, source='facebook')

            except Exception as e:
                log.debug(f'Error extracting post element: {e}')
                continue

    except PlaywrightTimeout:
        log.warning(f'Timeout loading group {group_url}')
    except Exception as e:
        log.error(f'Error scraping group {group_url}: {e}')

    log.info(f'Got {len(posts)} new posts from {group_url}')
    return posts


def scrape_all_groups(config: dict) -> list[dict]:
    """Scrape all configured Facebook groups. Returns all new posts."""
    group_urls = config.get('facebook_groups', [])
    if not group_urls:
        log.warning('No Facebook groups configured')
        return []

    all_posts = []

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

        for group_url in group_urls:
            posts = scrape_group(page, group_url)
            all_posts.extend(posts)
            time.sleep(random.uniform(2.0, 4.0))

        browser.close()

    return all_posts
