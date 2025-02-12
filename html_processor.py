import logging
import requests
from bs4 import BeautifulSoup
from captcha_dialog import CaptchaDialog
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QObject, QMetaObject, Qt, Slot
from utils import extract_domain, BASE_REQUEST_TIMEOUT
from config_manager import ConfigManager

class CaptchaHelper(QObject):
    def __init__(self, captcha_url, parent=None):
        super().__init__(parent)
        self.captcha_url = captcha_url
        self.captcha_code = None

    @Slot()
    def show_dialog(self):
        dialog = CaptchaDialog(self.captcha_url)
        if dialog.exec():
            self.captcha_code = dialog.get_captcha_text()
        else:
            self.captcha_code = None

class CaptchaErrorHelper(QObject):
    @Slot()
    def show_error(self):
        QMessageBox.critical(
            None,
            "CAPTCHA",
            "A CAPTCHA challenge was detected but no image could be extracted.\n"
            "It might be a reCAPTCHA or another unsupported format.\n"
            "Please solve the challenge manually in your browser."
        )

class HTMLResponseProcessor:
    def __init__(self, session: requests.Session, url: str):
        self.session = session
        self.url = url
        self.domain = extract_domain(url)

    def fetch_ghost_requests(self):
        ghost_urls = [
            f"https://{self.domain}/static/logo.png",
            f"https://{self.domain}/static/styles.css",
            f"https://{self.domain}/static/app.js"
        ]
        responses = []
        for ghost_url in ghost_urls:
            try:
                response = self.session.get(ghost_url, timeout=BASE_REQUEST_TIMEOUT)
                responses.append(response)
            except Exception as e:
                logging.debug("Ghost request error %s: %s", ghost_url, e)
        return responses

    def parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, 'lxml')

    def detect_honeypot(self, soup: BeautifulSoup) -> bool:
        for div in soup.find_all("div", style=lambda s: s and "display:none" in s):
            classes = div.get("class") or []
            div_id = div.get("id") or ""
            if any("honeypot" in cls.lower() for cls in classes) or "hidden" in div_id.lower():
                logging.warning("Honeypot detected on %s", self.url)
                return True
        return False

    def detect_captcha(self, soup: BeautifulSoup) -> bool:
        if soup.find(string=lambda text: text and "captcha" in text.lower()):
            logging.warning("CAPTCHA detected (text) on %s", self.url)
            return True
        if soup.find("img", id="captcha_image"):
            logging.warning("CAPTCHA image detected on %s", self.url)
            return True
        captcha_img = soup.find(lambda tag: tag.name == "img" and tag.get("src") and "captcha" in tag.get("src").lower())
        if captcha_img:
            logging.warning("CAPTCHA image detected by src on %s", self.url)
            return True
        return False

    def handle_captcha_manually(self, soup) -> str:
        config = ConfigManager().load()
        captcha_mode = config.get("captcha_mode", "manual")
        if captcha_mode == "disabled":
            raise Exception("CAPTCHA is disabled in config.")
        captcha_img = soup.find("img", id="captcha_image")
        if not captcha_img:
            captcha_img = soup.find(lambda tag: tag.name == "img" and tag.get("src") and "captcha" in tag.get("src").lower())
        if captcha_img and captcha_img.get("src"):
            captcha_url = captcha_img["src"]
            helper = CaptchaHelper(captcha_url)
            helper.moveToThread(QApplication.instance().thread())
            QMetaObject.invokeMethod(helper, "show_dialog", Qt.BlockingQueuedConnection)
            if helper.captcha_code:
                return helper.captcha_code
            else:
                raise Exception("No CAPTCHA code entered or canceled by user.")
        else:
            error_helper = CaptchaErrorHelper()
            error_helper.moveToThread(QApplication.instance().thread())
            QMetaObject.invokeMethod(error_helper, "show_error", Qt.BlockingQueuedConnection)
            raise Exception("CAPTCHA detected but no image extracted.")