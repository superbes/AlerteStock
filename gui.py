import sys, random, time, logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QSpinBox, QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QComboBox, QTabWidget, QFormLayout
)
from PySide6.QtCore import QTimer, Qt
from config_manager import ConfigManager
from utils import extract_domain, build_amazon_buy_link, create_interval_spinbox, ClickableLabel, BASE_REQUEST_TIMEOUT
from checkers import CheckerFactory, MAX_RETRIES, USER_AGENTS
try:
    import winsound
except ImportError:
    winsound = None

class StockCheckerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Stock Checker (Amazon, LDLC, Grosbill)")
        self.setMinimumSize(1200, 600)
        self.config_manager = ConfigManager()
        self.items = []  # List of monitored items (dicts)
        self.checkers = {}  # Key: URL, Value: checker thread
        self.updating_table = False  # Flag to prevent recursive updates
        self.setup_ui()
        self.setup_timers()
        self.load_config()
        self.apply_styles()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        # Surveillance Tab
        surveillance_tab = QWidget()
        surveillance_layout = QVBoxLayout(surveillance_tab)
        add_layout = QHBoxLayout()
        add_layout.addWidget(QLabel("URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Product URL (Amazon, LDLC or Grosbill)")
        add_layout.addWidget(self.url_input)
        add_layout.addWidget(QLabel("Interval (s):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 3600)
        self.interval_spin.setValue(60)
        add_layout.addWidget(self.interval_spin)
        add_layout.addWidget(QLabel("Price Limit:"))
        self.price_limit_input = QLineEdit()
        self.price_limit_input.setPlaceholderText("e.g. 1299.99")
        add_layout.addWidget(self.price_limit_input)
        self.add_button = QPushButton("Add Item")
        self.add_button.clicked.connect(self.add_item)
        add_layout.addWidget(self.add_button)
        surveillance_layout.addLayout(add_layout)
        self.table = QTableWidget()
        self.table.setColumnCount(13)
        self.table.setHorizontalHeaderLabels([
            "Name", "Domain", "Next Refresh", "Interval", "Price",
            "Price Limit", "Seller", "Shipper", "Status", "Actions", "Alerts", "Errors", "Delete"
        ])
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        surveillance_layout.addWidget(self.table)
        self.table.itemChanged.connect(self.handle_itemChanged)
        self.start_all_button = QPushButton("Start All")
        self.start_all_button.clicked.connect(self.start_all_items)
        surveillance_layout.addWidget(self.start_all_button)
        self.tabs.addTab(surveillance_tab, "Surveillance")
        # Configuration Tab
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        form_layout = QFormLayout()
        self.discord_webhook_input = QLineEdit()
        self.discord_webhook_input.setPlaceholderText("Discord Webhook (optional)")
        form_layout.addRow("Discord Webhook:", self.discord_webhook_input)
        self.discord_user_id_input = QLineEdit()
        self.discord_user_id_input.setPlaceholderText("User ID or 'everyone'")
        form_layout.addRow("User ID:", self.discord_user_id_input)
        self.captcha_mode_combo = QComboBox()
        self.captcha_mode_combo.addItem("Manual", "manual")
        self.captcha_mode_combo.addItem("Automatic", "automatic")
        self.captcha_mode_combo.addItem("Disabled", "disabled")
        form_layout.addRow("Captcha Mode:", self.captcha_mode_combo)
        config_layout.addLayout(form_layout)
        self.test_discord_button = QPushButton("Test Discord")
        self.test_discord_button.clicked.connect(self.test_discord)
        config_layout.addWidget(self.test_discord_button)
        self.tabs.addTab(config_tab, "Configuration")

    def setup_timers(self):
        self.global_timer = QTimer(self)
        self.global_timer.setInterval(1000)
        self.global_timer.timeout.connect(self.update_countdown)
        self.global_timer.start()

    def load_config(self):
        data = self.config_manager.load()
        self.discord_webhook_input.setText(data.get("discord_webhook", ""))
        self.discord_user_id_input.setText(data.get("discord_user_id", ""))
        captcha_mode = data.get("captcha_mode", "manual")
        index = self.captcha_mode_combo.findData(captcha_mode)
        if index >= 0:
            self.captcha_mode_combo.setCurrentIndex(index)
        articles = data.get("articles", [])
        for art in articles:
            self.add_item_from_config(art)

    def save_config(self):
        data = {
            "discord_webhook": self.discord_webhook_input.text().strip(),
            "discord_user_id": self.discord_user_id_input.text().strip(),
            "captcha_mode": self.captcha_mode_combo.currentData(),
            "articles": []
        }
        for item in self.items:
            alert_data = item.get("alert_type", [])
            data["articles"].append({
                "url": item["url"],
                "interval": item["interval"],
                "time_left": item["time_left"],
                "is_running": item["is_running"],
                "alert_type": alert_data,
                "auto_restart": item.get("auto_restart", False),
                "price_limit": item.get("price_limit", "")
            })
        self.config_manager.save(data)

    def closeEvent(self, event):
        for checker in self.checkers.values():
            checker.stop()
        for checker in self.checkers.values():
            checker.wait()
        self.save_config()
        event.accept()

    def add_item_from_config(self, art: dict):
        url = art.get("url", "").strip()
        if not url:
            return
        interval = art.get("interval", 60)
        offset = random.randint(0, interval)
        time_left = interval - offset
        item = {
            "url": url,
            "interval": interval,
            "time_left": time_left,
            "is_running": art.get("is_running", False),
            "alert_type": art.get("alert_type", []),
            "auto_restart": art.get("auto_restart", False),
            "price_limit": art.get("price_limit", "")
        }
        self._create_table_row(item)
        if item["is_running"]:
            self.toggle_item(item, item["row"], immediate=False)

    def add_item(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Please enter a product URL.")
            return
        for item in self.items:
            if item["url"].lower() == url.lower():
                QMessageBox.warning(self, "Duplicate", "This URL is already added.")
                return
        if not CheckerFactory.get_checker(url):
            QMessageBox.warning(self, "Unsupported Site", "This site is not supported.")
            return
        interval = self.interval_spin.value()
        offset = random.randint(0, interval)
        time_left = interval - offset
        price_limit = self.price_limit_input.text().strip()
        item = {
            "url": url,
            "interval": interval,
            "time_left": time_left,
            "is_running": False,
            "alert_type": [],
            "auto_restart": False,
            "price_limit": price_limit
        }
        self._create_table_row(item)
        self.url_input.clear()
        self.price_limit_input.clear()

    def _create_table_row(self, item: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item["row"] = row
        self.items.append(item)
        name_item = QTableWidgetItem("N/A")
        name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 0, name_item)
        domain = extract_domain(item["url"])
        buy_link = build_amazon_buy_link(item["url"]) if domain.endswith("amazon.fr") or domain.endswith("amazon.com.be") else item["url"]
        domain_label = ClickableLabel(domain, buy_link)
        self.table.setCellWidget(row, 1, domain_label)
        minutes, seconds = divmod(item["time_left"], 60)
        refresh_item = QTableWidgetItem("{:02d}:{:02d}".format(minutes, seconds))
        refresh_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 2, refresh_item)
        spinbox = create_interval_spinbox(item["interval"], lambda val, it=item: self.update_interval(it, val))
        self.table.setCellWidget(row, 3, spinbox)
        price_item = QTableWidgetItem("N/A")
        price_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 4, price_item)
        price_limit_text = item.get("price_limit", "") or "N/A"
        price_limit_item = QTableWidgetItem(price_limit_text)
        price_limit_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        self.table.setItem(row, 5, price_limit_item)
        seller_item = QTableWidgetItem("Unknown")
        seller_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 6, seller_item)
        shipper_item = QTableWidgetItem("Unknown")
        shipper_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 7, shipper_item)
        status_item = QTableWidgetItem("Paused")
        status_item.setForeground(Qt.red)
        status_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 8, status_item)
        start_pause_button = QPushButton("Start")
        start_pause_button.clicked.connect(lambda checked=False, it=item, r=row: self.toggle_item(it, r))
        self.table.setCellWidget(row, 9, start_pause_button)
        alert_combo = QComboBox()
        alert_combo.addItem("None", [])
        alert_combo.addItem("Discord", ["discord"])
        alert_combo.addItem("Sound", ["sound"])
        alert_combo.addItem("Both", ["discord", "sound"])
        if item.get("alert_type"):
            index = alert_combo.findData(item["alert_type"])
            if index >= 0:
                alert_combo.setCurrentIndex(index)
        alert_combo.currentIndexChanged.connect(lambda idx, it=item, combo=alert_combo: self.update_alert_type(it, combo.currentData()))
        self.table.setCellWidget(row, 10, alert_combo)
        item["alert_type"] = alert_combo.currentData()
        error_item = QTableWidgetItem("")
        error_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 11, error_item)
        remove_button = QPushButton("Delete")
        remove_button.clicked.connect(lambda checked=False, it=item, r=row: self.remove_item(it, r))
        self.table.setCellWidget(row, 12, remove_button)

    def handle_itemChanged(self, item: QTableWidgetItem):
        if self.updating_table:
            return
        if item.column() == 5:
            row = item.row()
            new_value = item.text().strip()
            try:
                self.items[row]["price_limit"] = new_value
            except IndexError:
                logging.error("Index out of range updating price limit at row %s", row)

    def update_alert_type(self, item: dict, value):
        item["alert_type"] = value

    def update_interval(self, item: dict, new_interval: int):
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

    def toggle_item(self, item: dict, row: int, immediate: bool = True):
        btn = self.table.cellWidget(row, 9)
        if item.get("is_running"):
            item["is_running"] = False
            item["auto_restart"] = False
            self._update_status(row, "Paused", Qt.red)
            btn.setText("Start")
            checker = self.checkers.get(item["url"])
            if checker:
                checker.stop()
        else:
            item["is_running"] = True
            item["auto_restart"] = True
            offset = random.randint(0, item["interval"])
            item["time_left"] = item["interval"] - offset
            self._update_status(row, "Monitoring...", Qt.darkGreen)
            btn.setText("Pause")
            if immediate:
                self.start_check(item)

    def _update_status(self, row: int, text: str, color: Qt.GlobalColor):
        status_item = QTableWidgetItem(text)
        status_item.setForeground(color)
        status_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 8, status_item)

    def update_countdown(self):
        for item in self.items:
            if (item.get("is_running", False) or item.get("auto_restart", False)) and item.get("time_left", 0) > 0:
                item["time_left"] -= 1
            row = item["row"]
            minutes, seconds = divmod(item["time_left"], 60)
            self.updating_table = True
            self.table.item(row, 2).setText("{:02d}:{:02d}".format(minutes, seconds))
            self.updating_table = False
            if item["time_left"] <= 0:
                if item.get("is_running", False):
                    jitter = int(item["interval"] * 0.1)
                    item["time_left"] = max(5, item["interval"] + random.randint(-jitter, jitter))
                    self.start_check(item)
                elif item.get("auto_restart", False):
                    item["is_running"] = True
                    self._update_status(item["row"], "Monitoring...", Qt.darkGreen)
                    btn = self.table.cellWidget(item["row"], 9)
                    btn.setText("Pause")
                    jitter = int(item["interval"] * 0.1)
                    item["time_left"] = max(5, item["interval"] + random.randint(-jitter, jitter))
                    self.start_check(item)

    def start_check(self, item: dict):
        checker = CheckerFactory.get_checker(item['url'])
        if checker:
            checker.setParent(self)
            checker.signals.update.connect(lambda data, it=item: self.update_item(it, data))
            checker.signals.error.connect(lambda error, it=item: self.handle_error(it, error))
            self.checkers[item['url']] = checker
            checker.start()

    def update_item(self, item: dict, data: dict):
        row = item["row"]
        self.updating_table = True
        if self.table.item(row, 0).text() == "N/A":
            self.table.item(row, 0).setText(data.get("name", "N/A"))
        price_str = data.get("price", "N/A")
        self.table.item(row, 4).setText(price_str)
        price_limit_str = item.get("price_limit", "").strip() or "N/A"
        self.table.item(row, 5).setText(price_limit_str)
        self.table.item(row, 6).setText(data.get("seller", "Unknown"))
        self.table.item(row, 7).setText(data.get("shipper", "Unknown"))
        status_text = data.get("status", "N/A")
        color = Qt.green if "en stock" in status_text.lower() else Qt.red
        if price_limit_str not in ["", "N/A"]:
            try:
                current_price = float(price_str.replace(',', '.').replace('€','').replace(' ', '').strip())
                limit_price = float(price_limit_str.replace(',', '.').replace('€','').replace(' ', '').strip())
                if current_price > limit_price:
                    status_text = "Price too high"
                    color = Qt.red
            except Exception as e:
                logging.error("Price conversion error: %s", e)
        self._update_status(row, status_text, color)
        self.table.item(row, 11).setText("")
        if "en stock" in status_text.lower():
            if price_limit_str in ["", "N/A"]:
                self.trigger_alerts(item, data)
                self.pause_item(item, row, 900, in_stock=True)
            else:
                try:
                    current_price = float(price_str.replace(',', '.').replace('€','').replace(' ', '').strip())
                    limit_price = float(price_limit_str.replace(',', '.').replace('€','').replace(' ', '').strip())
                    if current_price <= limit_price:
                        self.trigger_alerts(item, data)
                        self.pause_item(item, row, 900, in_stock=True)
                except Exception as e:
                    logging.error("Error comparing prices: %s", e)
        self.updating_table = False

    def handle_error(self, item: dict, error_data: dict):
        row = item["row"]
        error_msg = f"Error ({error_data['retries']}/{MAX_RETRIES}): {error_data['error']}"
        error_item = QTableWidgetItem(error_msg)
        error_item.setToolTip(f"Last error: {error_data['error']}")
        error_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        self.table.setItem(row, 11, error_item)
        if any(token in error_data['error'].lower() for token in ["429", "bloqu"]):
            self.pause_item(item, row, 900, in_stock=False)
        elif error_data['retries'] >= MAX_RETRIES:
            self.stop_check(item)

    def stop_check(self, item: dict):
        item["is_running"] = False
        row = item["row"]
        self._update_status(row, "Paused (error)", Qt.red)
        btn = self.table.cellWidget(row, 9)
        btn.setText("Start")
        if item["url"] in self.checkers:
            self.checkers[item["url"]].stop()

    def trigger_alerts(self, item: dict, data: dict):
        alerts = self.table.cellWidget(item["row"], 10).currentData()
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
            "🎉 **Good news!** 🎉\n\n"
            "The following product is now **in stock**:\n"
            "👉 **URL**: {}\n"
            "💰 **Price**: {}\n"
            "🏷 **Seller**: {}\n"
            "🚚 **Shipper**: {}\n\n"
            "Check it out!"
        ).format(
            item['url'],
            data.get('price', 'N/A'),
            data.get('seller', 'Unknown'),
            data.get('shipper', 'Unknown')
        )
        if user_id:
            if user_id.lower() == "everyone":
                content = "@everyone " + content
            else:
                content = f"<@{user_id}> " + content
        payload = {"content": content}
        try:
            self.session_post_discord(webhook_url, payload)
        except Exception as e:
            logging.error("Discord alert error: %s", e)

    def session_post_discord(self, webhook_url: str, payload: dict):
        import random
        import requests
        from checkers import USER_AGENTS
        session = requests.Session()
        session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        session.post(webhook_url, json=payload, timeout=BASE_REQUEST_TIMEOUT)

    def play_sound_alert(self):
        if winsound:
            winsound.Beep(2000, 500)
        else:
            logging.error("Sound alert requested but winsound is not available.")

    def pause_item(self, item: dict, row: int, pause_seconds: int, in_stock: bool = False):
        item["is_running"] = False
        item["time_left"] = pause_seconds
        item["auto_restart"] = True if in_stock else False
        status_text = f"IN STOCK! (Pause {pause_seconds // 60} min)" if in_stock else f"Paused ({pause_seconds // 60} min)"
        self._update_status(row, status_text, Qt.yellow)
        btn = self.table.cellWidget(row, 9)
        btn.setText("Start")

    def start_all_items(self):
        for item in self.items:
            if not item.get("is_running"):
                offset = random.randint(0, item["interval"])
                item["time_left"] = item["interval"] - offset
                row = item["row"]
                self.toggle_item(item, row, immediate=False)

    def apply_styles(self):
        style = """
        QMainWindow { background-color: #2c3e50; }
        QLabel, QTableWidgetItem { color: #ecf0f1; font-size: 14px; }
        QLineEdit, QSpinBox, QComboBox {
            background-color: #34495e; border: 1px solid #7f8c8d; padding: 4px;
            color: #ecf0f1; border-radius: 4px;
        }
        QComboBox QAbstractItemView {
            background-color: #34495e; color: #ecf0f1; selection-background-color: #2980b9;
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
        QTabWidget::pane { border: 0; background: #2c3e50; }
        QTabBar { background: #2c3e50; }
        QTabBar::tab {
            background: #34495e; color: #ecf0f1; padding: 10px;
            border: 1px solid #7f8c8d; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #2980b9; border-bottom: 2px solid #2c3e50;
        }
        QTabBar::tab:hover { background: #3d566e; }
        """
        self.setStyleSheet(style)

    def test_discord(self):
        if not self.items:
            QMessageBox.warning(self, "Empty List", "No items available for testing.")
            return
        item = random.choice(self.items)
        simulated_data = {
            "name": f"{item['url']} (Test)",
            "price": "123,45 €",
            "seller": "TestSeller",
            "shipper": "TestShipper",
            "status": "EN STOCK !"
        }
        self.send_discord_alert(item, simulated_data)
        QMessageBox.information(self, "Test Successful", "Test message sent successfully.")

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    window = StockCheckerApp()
    window.show()
    sys.exit(app.exec())