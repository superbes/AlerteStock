from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout
from PySide6.QtGui import QPixmap
import requests
from io import BytesIO

class CaptchaDialog(QDialog):
    def __init__(self, captcha_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CAPTCHA Resolution")
        self.captcha_url = captcha_url
        self.captcha_text = None
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        self.captcha_label = QLabel(self)
        try:
            response = requests.get(self.captcha_url, timeout=10)
            response.raise_for_status()
            image_data = BytesIO(response.content)
            pixmap = QPixmap()
            if pixmap.loadFromData(image_data.getvalue()):
                self.captcha_label.setPixmap(pixmap)
            else:
                self.captcha_label.setText("Unable to load CAPTCHA image")
        except Exception as e:
            self.captcha_label.setText(f"Error loading CAPTCHA: {e}")
        layout.addWidget(self.captcha_label)
        self.input_line = QLineEdit(self)
        self.input_line.setPlaceholderText("Enter CAPTCHA code")
        layout.addWidget(self.input_line)
        button_layout = QHBoxLayout()
        ok_button = QPushButton("OK", self)
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def accept(self):
        self.captcha_text = self.input_line.text().strip()
        super().accept()

    def get_captcha_text(self):
        return self.captcha_text