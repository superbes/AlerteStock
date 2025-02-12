import time
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from typing import Any, List, Dict
from utils import extract_domain

class StockTableModel(QAbstractTableModel):
    HEADERS = ["Name", "Domain", "Next Refresh", "Interval (s)", "Price", "Seller", "Shipper", "Status", "Alerts"]

    def __init__(self, items: List[Dict]) -> None:
        super().__init__()
        self.items = items

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid():
            return None
        item = self.items[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return item.get("name", "N/A")
            elif col == 1:
                return extract_domain(item["url"])
            elif col == 2:
                now = time.time()
                remaining = max(0, int(item.get("next_check_time", now) - now))
                minutes, seconds = divmod(remaining, 60)
                return f"{minutes:02d}:{seconds:02d}"
            elif col == 3:
                return item.get("interval", 60)
            elif col == 4:
                return item.get("price", "N/A")
            elif col == 5:
                return item.get("seller", "Unknown")
            elif col == 6:
                return item.get("shipper", "Unknown")
            elif col == 7:
                return item.get("status", "Paused")
            elif col == 8:
                alerts = item.get("alert_type", [])
                if not alerts:
                    return "None"
                elif alerts == ["discord"]:
                    return "Discord"
                elif alerts == ["sound"]:
                    return "Sound"
                elif alerts == ["discord", "sound"]:
                    return "Both"
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def update_item(self, row: int, data: Dict) -> None:
        self.items[row].update(data)
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount()-1))

    def add_item(self, item: Dict) -> None:
        self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
        self.items.append(item)
        self.endInsertRows()

    def remove_item(self, row: int) -> None:
        self.beginRemoveRows(QModelIndex(), row, row)
        self.items.pop(row)
        self.endRemoveRows()