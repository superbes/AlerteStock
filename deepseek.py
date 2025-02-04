import sys
import os
import json
import re
import logging
import random
import time
import threading
import requests
import webbrowser
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from typing import Dict, Optional

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QSpinBox, QMessageBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QComboBox
)
from PySide6.QtCore import QTimer, Qt, QThread, Signal, QObject
from PySide6.QtGui import QFont, QCursor

# Configuration du logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Pour jouer un son sous Windows
try:
    import winsound
except ImportError:
    winsound = None

# ---------------------------
# Constantes & Configuration
# ---------------------------
CONFIG_FILE = "config.json"
BASE_REQUEST_TIMEOUT = 15  # secondes de base pour le timeout
MAX_RETRIES = 3

# Liste d'User-Agents variés
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36",
    # Vous pouvez ajouter d'autres User-Agents ici
]

# Limitation du nombre de requêtes simultanées
CHECK_SEMAPHORE = threading.Semaphore(5)

# --------------------------------------
# Gestion de la configuration via un ConfigManager
# --------------------------------------
class ConfigManager:
    """Gestionnaire de configuration (chargement et sauvegarde)."""

    def __init__(self, filename: str = CONFIG_FILE):
        self.filename = filename

    def load(self) -> dict:
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logging.info("Configuration chargée depuis %s", self.filename)
                return data
            except Exception as e:
                logging.error("Erreur lors du chargement de la configuration : %s", e)
        return {}

    def save(self, data: dict):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            logging.info("Configuration sauvegardée dans %s", self.filename)
        except Exception as e:
            logging.error("Erreur lors de la sauvegarde de la configuration : %s", e)

# --------------------------------------
# Fonctions utilitaires pour les liens et domaines
# --------------------------------------
def extract_asin(url: str) -> Optional[str]:
    """
    Extrait l'ASIN d'une URL Amazon.
    On teste différents patterns (ex: /dp/ASIN, /gp/product/ASIN, etc.).
    """
    patterns = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/product/([A-Z0-9]{10})"
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    # Dernier recours : récupération du paramètre ASIN dans la query string
    parsed = urlparse(url)
    qs = parsed.query
    params = dict(part.split('=', 1) for part in qs.split('&') if '=' in part)
    return params.get("ASIN")

def extract_domain(url: str) -> str:
    """Extrait le domaine d'une URL (ex: amazon.fr, ldlc.com, grosbill.com, etc.)."""
    parsed = urlparse(url)
    return parsed.netloc.lower() if parsed.netloc else "N/A"

def build_amazon_buy_link(url: str) -> str:
    """
    Construit le lien d'achat direct pour Amazon si le domaine est .fr ou .com.be.
    """
    domain = extract_domain(url)
    if not (domain.endswith("amazon.fr") or domain.endswith("amazon.com.be")):
        return url
    asin = extract_asin(url)
    if not asin:
        return url
    return f"https://{domain}/gp/product/handle-buy-box/ref=dp_start-bbf_1_glance?ASIN={asin}&quantity=1&submit.buy-now=1"

# ---------------------------------
# Classe pour une étiquette cliquable
# ---------------------------------
class ClickableLabel(QLabel):
    def __init__(self, text: str, link: str, parent=None):
        super().__init__(parent)
        self.link = link
        self.setText(f'<a href="{self.link}">{text}</a>')
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.setOpenExternalLinks(True)

# ------------------------------
# Système de vérification en thread
# ------------------------------
class CheckerSignal(QObject):
    update = Signal(dict)
    error = Signal(dict)

class BaseChecker(QThread):
    """
    Classe de base pour la vérification de stock.
    Les classes filles doivent implémenter check_stock().
    """
    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self.session = requests.Session()
        # Construction d'en-têtes variés
        self.headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self._generate_referer(url),
            "DNT": str(random.randint(0, 1))  # Do Not Track aléatoire
        }
        # Ajustements par domaine
        domain = extract_domain(url)
        if "amazon.fr" in domain:
            self.headers["Accept-Language"] = "fr-FR,fr;q=0.9"
        self.session.headers.update(self.headers)

        self.signals = CheckerSignal()
        self.running = True
        self.retries = 0

    def _generate_referer(self, url: str) -> str:
        """Génère un Referer plausible (page d'accueil)."""
        domain = extract_domain(url)
        return f"https://{domain}/"

    def run(self):
        while self.running and self.retries < MAX_RETRIES:
            # Limiter le nombre de requêtes simultanées
            with CHECK_SEMAPHORE:
                # Attente aléatoire entre 0.5 et 3 secondes pour éviter la régularité robotique
                time.sleep(random.uniform(0.5, 3.0))
                try:
                    result = self.check_stock()
                    self.signals.update.emit(result)
                    self.running = False  # Arrêt après succès
                except Exception as e:
                    self.retries += 1
                    error_data = {
                        "url": self.url,
                        "error": str(e),
                        "retries": self.retries
                    }
                    logging.error("Erreur pour %s: %s", self.url, str(e))
                    self.signals.error.emit(error_data)
                    self.msleep(2000 * self.retries)  # Backoff exponentiel

    def check_stock(self) -> Dict:
        raise NotImplementedError

    def stop(self):
        self.running = False

class AmazonChecker(BaseChecker):
    def check_stock(self) -> Dict:
        # Variation aléatoire du timeout
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        domain = extract_domain(self.url)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        title_elem = soup.find("span", id="productTitle")
        if title_elem is None:
            asin = extract_asin(self.url)
            if asin:
                product_url = f"https://{domain}/dp/{asin}"
                response2 = self.session.get(product_url, timeout=timeout)
                response2.raise_for_status()
                soup2 = BeautifulSoup(response2.text, 'html.parser')
                title_elem = soup2.find("span", id="productTitle")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"

        price_elem = soup.find("span", class_="a-offscreen")
        price = price_elem.get_text(strip=True) if price_elem else "N/A"
        # Correction du prix indésirable
        if "Page 1 sur 1" in price or "Seite 1 von 1" in price:
            price = "N/A"

        seller_elem = soup.find("a", id="sellerProfileTriggerId")
        seller = seller_elem.get_text(strip=True) if seller_elem else "Amazon"
        shipped_elem = soup.find("span", class_="a-size-small offer-display-feature-text-message")
        shipper = shipped_elem.get_text(strip=True) if shipped_elem else "Inconnu"

        status = "EN STOCK !" if price != "N/A" and seller and shipper != "Inconnu" else "Indisponible"

        return {
            "name": name,
            "price": price,
            "seller": seller,
            "shipper": shipper,
            "status": status
        }

class LDLChecker(BaseChecker):
    def check_stock(self) -> Dict:
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        title_elem = soup.find("h1", class_="title-1")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"

        price_div = soup.find("div", class_="price")
        if price_div:
            raw_price = price_div.get_text(strip=True).replace("\xa0", "")
            match = re.match(r"(\d+)\s*€\s*(\d+)", raw_price)
            if match:
                price_text = f"{match.group(1)},{match.group(2)} €"
            else:
                price_text = raw_price
        else:
            price_text = "N/A"

        seller = "LDLC"
        shipper = "LDLC"

        stock_div = soup.find("div", class_="modal-stock-web")
        status = "EN STOCK !" if stock_div and stock_div.get("data-stock-web", "") == "1" else "Rupture"

        return {
            "name": name,
            "price": price_text,
            "seller": seller,
            "shipper": shipper,
            "status": status
        }

class GrosbillChecker(BaseChecker):
    def check_stock(self) -> Dict:
        timeout = BASE_REQUEST_TIMEOUT + random.uniform(-2, 2)
        response = self.session.get(self.url, timeout=timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        title_elem = soup.find("h1", id="_ctl0_ContentPlaceHolder1_titre_produit_top", class_="grb_product-page__title")
        name = title_elem.get_text(strip=True) if title_elem else "N/A"

        price_elem = soup.find("span", class_="p-3x")
        price = price_elem.get_text(strip=True) if price_elem else "N/A"

        seller = "Grosbill"
        shipper = "Grosbill"

        availability_elem = soup.find(string=re.compile(r"NON\s*DISPONIBLE", re.IGNORECASE))
        status = "NON DISPONIBLE" if availability_elem else ("EN STOCK !" if price != "N/A" else "Indisponible")

        return {
            "name": name,
            "price": price,
            "seller": seller,
            "shipper": shipper,
            "status": status
        }

class CheckerFactory:
    """Factory pour retourner le checker adapté selon le domaine."""
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

# --------------------------------------
# Fonctions d'aide pour la création de widgets
# --------------------------------------
def create_interval_spinbox(interval: int, callback):
    """
    Crée un QSpinBox pour l'intervalle avec une plage de 5 à 3600 secondes.
    Le signal valueChanged est connecté à callback.
    """
    spinbox = QSpinBox()
    spinbox.setRange(5, 3600)
    spinbox.setValue(interval)
    spinbox.valueChanged.connect(callback)
    return spinbox

# --------------------------------------
# Application principale
# --------------------------------------
class StockCheckerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Vérificateur de Stock (Amazon, LDLC, Grosbill)")
        self.setMinimumSize(1200, 600)

        self.config_manager = ConfigManager()
        self.items = []      # Liste des articles surveillés (dictionnaires)
        self.checkers = {}   # Clé : URL, valeur : thread de vérification

        self.setup_ui()
        self.setup_timers()
        self.load_config()
        self.apply_styles()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # Zone de configuration Discord
        config_layout = QHBoxLayout()
        config_layout.addWidget(QLabel("Webhook Discord :"))
        self.discord_webhook_input = QLineEdit()
        self.discord_webhook_input.setPlaceholderText("Webhook Discord (facultatif)")
        config_layout.addWidget(self.discord_webhook_input)
        config_layout.addWidget(QLabel("User ID :"))
        self.discord_user_id_input = QLineEdit()
        self.discord_user_id_input.setPlaceholderText("ID utilisateur à ping (facultatif)")
        config_layout.addWidget(self.discord_user_id_input)

        # Zone d'ajout d'un article
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("URL :"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("URL du produit (Amazon, LDLC ou Grosbill)")
        self.url_input.setToolTip("URLs supportées:\n- Amazon\n- LDLC\n- Grosbill")
        add_layout.addWidget(self.url_input)
        add_layout.addWidget(QLabel("Intervalle (s) :"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(60)
        self.interval_spin.setToolTip("Intervalle entre les vérifications (min: 5s, max: 1h)")
        add_layout.addWidget(self.interval_spin)
        self.add_button = QPushButton("Ajouter l'article")
        add_layout.addWidget(self.add_button)
        self.add_button.clicked.connect(self.add_item)

        # Tableau de suivi (12 colonnes)
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Nom", "Domaine", "Prochain Refresh", "Intervalle", "Prix",
            "Vendeur", "Expéditeur", "Statut", "Actions", "Alertes", "Erreurs", "Suppr."
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)

        main_layout.addLayout(config_layout)
        main_layout.addLayout(add_layout)
        main_layout.addWidget(self.table)

    def setup_timers(self):
        self.global_timer = QTimer(self)
        self.global_timer.setInterval(1000)
        self.global_timer.timeout.connect(self.update_countdown)
        self.global_timer.start()

    def load_config(self):
        data = self.config_manager.load()
        self.discord_webhook_input.setText(data.get("discord_webhook", ""))
        self.discord_user_id_input.setText(data.get("discord_user_id", ""))
        articles = data.get("articles", [])
        for art in articles:
            self.add_item_from_config(art)

    def save_config(self):
        data = {
            "discord_webhook": self.discord_webhook_input.text().strip(),
            "discord_user_id": self.discord_user_id_input.text().strip(),
            "articles": []
        }
        for item in self.items:
            alert_data = item.get("alert_type", [])
            data["articles"].append({
                "url": item["url"],
                "interval": item["interval"],
                "time_left": item["time_left"],
                "is_running": item["is_running"],
                "alert_type": alert_data
            })
        self.config_manager.save(data)

    def closeEvent(self, event):
        self.save_config()
        event.accept()

    def add_item_from_config(self, art: dict):
        url = art.get("url", "").strip()
        if not url:
            return
        interval = art.get("interval", 60)
        item = {
            "url": url,
            "interval": interval,
            "time_left": art.get("time_left", interval),
            "is_running": art.get("is_running", False),
            "alert_type": art.get("alert_type", [])
        }
        self._create_table_row(item)

        # Démarrage automatique si l'article était en surveillance dans la config
        if item["is_running"]:
            self.toggle_item(item, item["row"])

    def add_item(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "URL manquante", "Veuillez saisir l'URL du produit.")
            return
        if not CheckerFactory.get_checker(url):
            QMessageBox.warning(self, "Site non supporté", "Ce site n'est pas actuellement pris en charge.")
            return
        interval = self.interval_spin.value()
        item = {
            "url": url,
            "interval": interval,
            "time_left": interval,
            "is_running": False,
            "alert_type": []
        }
        self._create_table_row(item)
        self.url_input.clear()

    def _create_table_row(self, item: dict):
        """Création d'une ligne dans le tableau pour l'article donné."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        item["row"] = row
        self.items.append(item)

        # Colonne Nom
        self.table.setItem(row, 0, QTableWidgetItem("N/A"))
        # Colonne Domaine avec lien cliquable
        domain = extract_domain(item["url"])
        buy_link = build_amazon_buy_link(item["url"]) if domain.endswith("amazon.fr") or domain.endswith("amazon.com.be") else item["url"]
        domain_label = ClickableLabel(domain, buy_link)
        self.table.setCellWidget(row, 1, domain_label)
        # Colonne Prochain Refresh
        self.table.setItem(row, 2, QTableWidgetItem("00:00"))
        # Colonne Intervalle (avec QSpinBox)
        spinbox = create_interval_spinbox(item["interval"], lambda val, it=item: self.update_interval(it, val))
        self.table.setCellWidget(row, 3, spinbox)
        # Colonne Prix
        self.table.setItem(row, 4, QTableWidgetItem("N/A"))
        # Colonne Vendeur
        self.table.setItem(row, 5, QTableWidgetItem("Inconnu"))
        # Colonne Expéditeur
        self.table.setItem(row, 6, QTableWidgetItem("Inconnu"))
        # Colonne Statut
        status_item = QTableWidgetItem("En pause")
        status_item.setForeground(Qt.red)
        self.table.setItem(row, 7, status_item)
        # Colonne Actions (Bouton démarrer/pause)
        start_pause_button = QPushButton("Démarrer")
        start_pause_button.clicked.connect(lambda checked=False, it=item, r=row: self.toggle_item(it, r))
        self.table.setCellWidget(row, 8, start_pause_button)
        # Colonne Alertes (QComboBox)
        alert_combo = QComboBox()
        alert_combo.addItem("Aucune", [])
        alert_combo.addItem("Discord", ["discord"])
        alert_combo.addItem("Son", ["sound"])
        alert_combo.addItem("Les deux", ["discord", "sound"])
        # Si une alerte était sauvegardée dans la config
        if item.get("alert_type"):
            index = alert_combo.findData(item["alert_type"])
            if index >= 0:
                alert_combo.setCurrentIndex(index)
        self.table.setCellWidget(row, 9, alert_combo)
        item["alert_type"] = alert_combo.currentData()
        # Colonne Erreurs
        self.table.setItem(row, 10, QTableWidgetItem(""))
        # Colonne Suppr. (Bouton supprimer)
        remove_button = QPushButton("Supprimer")
        remove_button.clicked.connect(lambda checked=False, it=item, r=row: self.remove_item(it, r))
        self.table.setCellWidget(row, 11, remove_button)

    def update_interval(self, item: dict, new_interval: int):
        """Met à jour l'intervalle de vérification pour l'article."""
        logging.info("Mise à jour de l'intervalle pour %s: %d", item["url"], new_interval)
        item["interval"] = new_interval
        if item["time_left"] > new_interval:
            item["time_left"] = new_interval

    def remove_item(self, item: dict, row: int):
        if item in self.items:
            self.items.remove(item)
        self.table.removeRow(row)
        self.reindex_table()

    def reindex_table(self):
        for i, it in enumerate(self.items):
            it["row"] = i

    def toggle_item(self, item: dict, row: int):
        if item["is_running"]:
            # Passage en pause
            item["is_running"] = False
            self._update_status(row, "En pause", Qt.red)
            btn = self.table.cellWidget(row, 8)
            btn.setText("Démarrer")
            checker = self.checkers.get(item["url"])
            if checker:
                checker.stop()
        else:
            # Démarrage de la vérification
            item["is_running"] = True
            self.start_check(item)
            self._update_status(row, "Surveillance en cours...", Qt.darkGreen)
            btn = self.table.cellWidget(row, 8)
            btn.setText("Pause")

    def _update_status(self, row: int, text: str, color: Qt.GlobalColor):
        status_item = QTableWidgetItem(text)
        status_item.setForeground(color)
        self.table.setItem(row, 7, status_item)

    def update_countdown(self):
        for item in self.items:
            if item["is_running"]:
                item["time_left"] -= 1
                row = item["row"]
                if item["time_left"] <= 0:
                    # Réinitialisation avec jitter (±10% de l'intervalle)
                    jitter = int(item["interval"] * 0.1)
                    item["time_left"] = item["interval"] + random.randint(-jitter, jitter)
                    item["time_left"] = max(5, item["time_left"])  # Minimum 5s
                    self.start_check(item)
                minutes, seconds = divmod(item["time_left"], 60)
                time_str = f"{minutes:02d}:{seconds:02d}"
                self.table.setItem(row, 2, QTableWidgetItem(time_str))

    def start_check(self, item: dict):
        checker = CheckerFactory.get_checker(item['url'])
        if checker:
            # Connexion des signaux pour mettre à jour l'interface
            checker.signals.update.connect(lambda data, it=item: self.update_item(it, data))
            checker.signals.error.connect(lambda error, it=item: self.handle_error(it, error))
            self.checkers[item['url']] = checker
            checker.start()

    def update_item(self, item: dict, data: dict):
        row = item["row"]
        if self.table.item(row, 0).text() == "N/A":
            self.table.setItem(row, 0, QTableWidgetItem(data.get("name", "N/A")))
        self.table.setItem(row, 4, QTableWidgetItem(data.get("price", "N/A")))
        self.table.setItem(row, 5, QTableWidgetItem(data.get("seller", "Inconnu")))
        self.table.setItem(row, 6, QTableWidgetItem(data.get("shipper", "Inconnu")))
        status_text = data.get("status", "N/A")
        color = Qt.green if "en stock" in status_text.lower() else Qt.red
        self._update_status(row, status_text, color)
        self.table.setItem(row, 10, QTableWidgetItem(""))
        if "en stock" in status_text.lower():
            self.trigger_alerts(item, data)
            self.pause_item(item, row, 300, in_stock=True)

    def handle_error(self, item: dict, error_data: dict):
        row = item["row"]
        error_msg = f"Erreur ({error_data['retries']}/{MAX_RETRIES}): {error_data['error']}"
        error_item = QTableWidgetItem(error_msg)
        error_item.setToolTip(f"Dernière erreur: {error_data['error']}")
        self.table.setItem(row, 10, error_item)
        if any(token in error_data['error'].lower() for token in ["429", "bloqu"]):
            self.pause_item(item, row, 900, in_stock=False)
        elif error_data['retries'] >= MAX_RETRIES:
            self.stop_check(item)

    def stop_check(self, item: dict):
        item["is_running"] = False
        row = item["row"]
        self._update_status(row, "En pause (erreur)", Qt.red)
        btn = self.table.cellWidget(row, 8)
        btn.setText("Démarrer")
        if item["url"] in self.checkers:
            self.checkers[item["url"]].stop()

    def trigger_alerts(self, item: dict, data: dict):
        alerts = self.table.cellWidget(item["row"], 9).currentData()
        if not alerts:
            return
        if "discord" in alerts:
            self.send_discord_alert(item, data)
        if "sound" in alerts:
            self.play_sound_alert()

    def send_discord_alert(self, item: dict, data: dict):
        webhook_url = self.discord_webhook_input.text().strip()
        user_id = self.discord_user_id_input.text().strip()
        if not webhook_url:
            return
        content = (
            f"🎉 **Bonne nouvelle !** 🎉\n\n"
            f"Le produit suivant est désormais **en stock** :\n"
            f"👉 **URL** : {item['url']}\n"
            f"💰 **Prix** : {data.get('price', 'N/A')}\n"
            f"🏷 **Vendu par** : {data.get('seller', 'Inconnu')}\n"
            f"🚚 **Expédié par** : {data.get('shipper', 'Inconnu')}\n\n"
            f"Foncez jeter un œil !"
        )
        if user_id:
            content = f"<@{user_id}> {content}"
        payload = {"content": content}
        try:
            self.session_post_discord(webhook_url, payload)
        except Exception as e:
            logging.error("Erreur envoi Discord : %s", e)

    def session_post_discord(self, webhook_url: str, payload: dict):
        # Utilisation d'une session persistante pour l'envoi
        session = requests.Session()
        session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        session.post(webhook_url, json=payload, timeout=BASE_REQUEST_TIMEOUT)

    def play_sound_alert(self):
        if winsound:
            winsound.Beep(2000, 500)  # fréquence 2000Hz, durée 500ms
        else:
            logging.warning("Alerte sonore demandée, mais winsound n'est pas disponible.")

    def pause_item(self, item: dict, row: int, pause_seconds: int, in_stock: bool = False):
        item["is_running"] = False
        item["time_left"] = pause_seconds
        status_text = f"EN STOCK! (Pause {pause_seconds//60} min)" if in_stock else f"Pause ({pause_seconds//60} min)"
        self._update_status(row, status_text, Qt.yellow)
        btn = self.table.cellWidget(row, 8)
        btn.setText("Démarrer")

    def apply_styles(self):
        style = """
        QMainWindow { background-color: #2c3e50; }
        QLabel, QTableWidgetItem { color: #ecf0f1; font-size: 14px; }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #34495e; border: 1px solid #7f8c8d; padding: 4px;
            color: #ecf0f1; border-radius: 4px;
        }
        QPushButton {
            background-color: #3498db; border: none; color: #ecf0f1;
            padding: 6px 12px; border-radius: 4px; font-size: 14px;
        }
        QPushButton:hover { background-color: #2980b9; }
        QTableWidget {
            background-color: #34495e; alternate-background-color: #3d566e; gridline-color: #7f8c8d;
        }
        QHeaderView::section {
            background-color: #2980b9; color: #ecf0f1; padding: 4px; border: none;
        }
        """
        self.setStyleSheet(style)

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StockCheckerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
