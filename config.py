import os
import json
from pathlib import Path

class Config:
    def __init__(self):
        self.config_file = "config.json"
        self.config = self._load_config()
    
    def _load_config(self):
        """Загружает конфигурацию"""
        if Path(self.config_file).exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            "openai_api_key": "",
            "openai_model": "o4-mini-2025-04-16"
        }
    
    def save_config(self):
        """Сохраняет конфигурацию"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
            return False
    
    def get_openai_key(self):
        """Получает OpenAI API ключ"""
        return self.config.get("openai_api_key", "")
    
    def set_openai_key(self, api_key):
        """Устанавливает OpenAI API ключ"""
        self.config["openai_api_key"] = api_key
        return self.save_config()
    
    def is_ai_enabled(self):
        """Проверяет, включена ли AI оптимизация (теперь зависит только от наличия ключа)."""
        return bool(self.get_openai_key())
    
    def get_openai_model(self):
        """Получает модель OpenAI"""
        return self.config.get("openai_model", "o4-mini-2025-04-16")
    
    def get_price_variance_threshold(self):
        """Получает максимальный процент расхождения цен в кластерах"""
        return self.config.get("price_variance_threshold", 25.0)

# Глобальный экземпляр конфигурации
config = Config() 