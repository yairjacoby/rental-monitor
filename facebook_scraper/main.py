import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from seen_store import init_db
from scraper_facebook import scrape_all_groups
# from scraper_yad2 import scrape_yad2
# from scraper_madlan import scrape_madlan
from parser_claude import parse_listings
from notifier_telegram import send_alert
from config_loader import load_config

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

def run_cycle():
    log.info('--- Cycle start ---')
    config = load_config()
    raw_posts = scrape_all_groups(config)
    log.info(f'Scraped {len(raw_posts)} new posts')
    parsed = parse_listings(raw_posts, config)
    log.info(f'Parsed {len(parsed)} matching listings')
    for listing in parsed:
        send_alert(listing)
    log.info('--- Cycle end ---')

if __name__ == '__main__':
    init_db()
    log.info('Rental monitor started')
    run_cycle()  # run immediately on start
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, 'interval', minutes=15)
    scheduler.start()
