import os
import json
import logging

CONFIG_FILE = "config.json"

class ConfigManager:
    def __init__(self, filename: str = CONFIG_FILE) -> None:
        self.filename = filename

    def load(self) -> dict:
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data
            except Exception as e:
                logging.error("Error loading config: %s", e)
        return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logging.error("Error saving config: %s", e)