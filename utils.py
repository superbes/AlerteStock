import re
from urllib.parse import urlparse
from typing import Optional
from PySide6.QtWidgets import QSpinBox, QLabel
from PySide6.QtCore import Qt

BASE_REQUEST_TIMEOUT = 15

def extract_asin(url: str) -> Optional[str]:
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})"
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    parsed = urlparse(url)
    qs = parsed.query
    if qs:
        try:
            params = dict(part.split('=', 1) for part in qs.split('&') if '=' in part)
            return params.get("ASIN")
        except Exception:
            return None
    return None

def extract_domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() if parsed.netloc else "N/A"

def build_amazon_buy_link(url: str) -> str:
    domain = extract_domain(url)
    if not (domain.endswith("amazon.fr") or domain.endswith("amazon.com.be")):
        return url
    asin = extract_asin(url)
    if not asin:
        return url
    return f"https://{domain}/gp/product/handle-buy-box/ref=dp_start-bbf_1_glance?ASIN={asin}&quantity=1&submit.buy-now=1"

def create_interval_spinbox(interval: int, callback):
    spinbox = QSpinBox()
    spinbox.setRange(5, 3600)
    spinbox.setValue(interval)
    spinbox.valueChanged.connect(callback)
    return spinbox

class ClickableLabel(QLabel):
    def __init__(self, text: str, link: str, parent=None):
        super().__init__(parent)
        self.link = link
        self.setText(f'<a href="{self.link}">{text}</a>')
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.setOpenExternalLinks(True)

def parse_price(price_str: str) -> Optional[float]:
    if not price_str or price_str == "N/A":
        return None
    try:
        cleaned = price_str.replace("€", "").replace(" ", "").strip().replace(",", ".")
        return float(cleaned)
    except ValueError:
        return None