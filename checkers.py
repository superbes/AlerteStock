import time
import random
import logging
import threading
import requests
from typing import Dict, Optional
from bs4 import BeautifulSoup
from utils import extract_asin, extract_domain, BASE_REQUEST_TIMEOUT
from PySide6.QtCore import QThread, QObject, Signal

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0"
]

CHECK_SEMAPHORE = threading.Semaphore(5)
MAX_RETRIES = 3

class CheckerSignal(QObject):
    update = Signal(dict)
    error = Signal(dict)

class BaseChecker(QThread):
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.session = requests.Session()
        self.session.cookies.update({"session-id": "simulate-session-id-123456"})
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self._generate_referer(url),
            "DNT": str(random.randint(0, 1))
        }
        domain = extract_domain(url)
        if "amazon.fr" in domain:
            self.headers["Accept-Language"] = "fr-FR,fr;q=0.9"
        self.session.headers.update(self.headers)
        self.signals = CheckerSignal()
        self.running = True
        self.retries = 0

    def _generate_referer(self, url: str) -> str:
        domain = extract_domain(url)
        return f"https://{domain}/"

    def fetch_ghost_requests(self, url: str):
        domain = extract_domain(url)
        ghost_urls = [
            f"https://{domain}/static/logo.png",
            f"https://{domain}/static/styles.css",
            f"https://{domain}/static/app.js"
        ]
        for ghost_url in ghost_urls:
            try:
                time.sleep(random.uniform(0.1, 0.3))
                self.session.get(ghost_url, timeout=BASE_REQUEST_TIMEOUT)
            except Exception as e:
                logging.debug("Ghost request error %s: %s", ghost_url, e)

    def run(self):
        self.fetch_ghost_requests(self.url)
        while self.running and self.retries < MAX_RETRIES:
            with CHECK_SEMAPHORE:
                time.sleep(random.uniform(0.5, 3.0))
                try:
                    result = self.check_stock()
                    self.signals.update.emit(result)
                    self.running = False
                except Exception as e:
                    self.retries += 1
                    error_data = {"url": self.url, "error": str(e), "retries": self.retries}
                    logging.error("Error for %s: %s", self.url, str(e))
                    self.signals.error.emit(error_data)
                    self.msleep(2000 * self.retries)

    def check_stock(self) -> Dict:
        raise NotImplementedError

    def stop(self):
        self.running = False

from html_processor import HTMLResponseProcessor

class AmazonChecker(BaseChecker):
    def check_stock(self) -> Dict:
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        processor = HTMLResponseProcessor(self.session, self.url)
        processor.fetch_ghost_requests()
        soup = processor.parse_html(response.text)
        if processor.detect_honeypot(soup):
            raise Exception("Honeypot detected")
        if processor.detect_captcha(soup):
            try:
                captcha_code = processor.handle_captcha_manually(soup)
                payload = {"captcha": captcha_code}
                response = self.session.post(self.url, data=payload, timeout=timeout)
                response.raise_for_status()
                soup = processor.parse_html(response.text)
            except Exception as e:
                raise Exception(f"CAPTCHA resolution error: {e}")
        title_elem = soup.find("span", id="productTitle")
        if title_elem is None:
            asin = extract_asin(self.url)
            if asin:
                product_url = "https://{}/dp/{}".format(extract_domain(self.url), asin)
                response2 = self.session.get(product_url, timeout=timeout)
                response2.raise_for_status()
                soup = processor.parse_html(response2.text)
                title_elem = soup.find("span", id="productTitle")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"
        price_elem = soup.find("span", class_="a-offscreen")
        price = price_elem.get_text(strip=True) if price_elem else "N/A"
        if "Page 1 sur 1" in price or "Seite 1 von 1" in price:
            price = "N/A"
        seller_elem = soup.find("a", id="sellerProfileTriggerId")
        seller = seller_elem.get_text(strip=True) if seller_elem else "Amazon"
        shipped_elem = soup.find("span", class_="a-size-small offer-display-feature-text-message")
        shipper = shipped_elem.get_text(strip=True) if shipped_elem else "Unknown"
        status = "EN STOCK !" if price != "N/A" and seller and shipper != "Unknown" else "Unavailable"
        return {"name": name, "price": price, "seller": seller, "shipper": shipper, "status": status}

class LDLChecker(BaseChecker):
    def check_stock(self) -> Dict:
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        processor = HTMLResponseProcessor(self.session, self.url)
        processor.fetch_ghost_requests()
        soup = processor.parse_html(response.text)
        if processor.detect_honeypot(soup):
            raise Exception("Honeypot detected")
        if processor.detect_captcha(soup):
            raise Exception("CAPTCHA detected")
        title_elem = soup.find("h1", class_="title-1")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"
        price_div = soup.find("div", class_="price")
        if price_div:
            raw_price = price_div.get_text(strip=True).replace("\xa0", "")
            import re
            match = re.match(r"(\d+)\s*€\s*(\d+)", raw_price)
            price_text = "{} €".format(match.group(1) + "," + match.group(2)) if match else raw_price
        else:
            price_text = "N/A"
        seller = "LDLC"
        shipper = "LDLC"
        stock_div = soup.find("div", class_="modal-stock-web")
        status = "EN STOCK !" if stock_div and stock_div.get("data-stock-web", "") == "1" else "Out of stock"
        return {"name": name, "price": price_text, "seller": seller, "shipper": shipper, "status": status}

class GrosbillChecker(BaseChecker):
    def check_stock(self) -> Dict:
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        processor = HTMLResponseProcessor(self.session, self.url)
        processor.fetch_ghost_requests()
        soup = processor.parse_html(response.text)
        if processor.detect_honeypot(soup):
            raise Exception("Honeypot detected")
        if processor.detect_captcha(soup):
            raise Exception("CAPTCHA detected")
        title_elem = soup.find("h1", id="_ctl0_ContentPlaceHolder1_titre_produit_top", class_="grb_product-page__title")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"
        price_elem = soup.find("span", class_="p-3x")
        price = price_elem.get_text(strip=True) if price_elem else "N/A"
        seller = "Grosbill"
        shipper = "Grosbill"
        import re
        availability_elem = soup.find(string=re.compile(r"NON\s*DISPONIBLE", re.IGNORECASE))
        status = "Unavailable" if availability_elem else ("EN STOCK !" if price != "N/A" else "Unavailable")
        return {"name": name, "price": price, "seller": seller, "shipper": shipper, "status": status}

class CheckerFactory:
    @staticmethod
    def get_checker(url: str) -> Optional[BaseChecker]:
        domain = extract_domain(url)
        if "ldlc.com" in domain:
            return LDLChecker(url)
        elif "grosbill.com" in domain:
            return GrosbillChecker(url)
        elif "amazon." in domain:
            return AmazonChecker(url)
        return None