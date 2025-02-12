import sys
from PySide6.QtWidgets import QApplication
from gui import StockCheckerApp

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StockCheckerApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
