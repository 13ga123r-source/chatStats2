import gspread
from google.oauth2.service_account import Credentials
import os
import logging

logger = logging.getLogger(__name__)

# Чтение переменных окружения
CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '')
ENABLED = os.environ.get('ENABLE_GOOGLE_SHEETS', 'false').lower() == 'true'
USE_CHAT_LINK = os.environ.get('USE_CHAT_LINK', 'true').lower() == 'true'

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def append_record(record_data):
    logger.info("🔍 append_record вызвана")
    """Добавляет строку в Google Таблицу, если функция включена."""
    if not ENABLED:
        logger.debug("Запись в Google Sheets отключена")
        return

    if not SHEET_ID:
        logger.warning("Google Sheet ID не задан, пропускаем запись")
        return

    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("logs")  # можно заменить на .worksheet("Имя листа")

        # Формируем значение для conversation_id (ссылку или просто ID)
        conv_id = record_data.get('conversation_id', '')
        if USE_CHAT_LINK and conv_id:
            chat_value = f"https://chat.moneyman.ru/operator/chat/{conv_id}"
        else:
            chat_value = conv_id

        # Порядок колонок должен соответствовать заголовкам в таблице
        row = [
            record_data.get('operator_name', ''),
            chat_value,   # здесь будет ссылка или просто ID
            record_data.get('closed_at_utc', ''),
            record_data.get('queue_name', ''),
            record_data.get('timestamp', '')
        ]
        sheet.append_row(row)
        logger.info(f"✅ Запись в Google Sheets добавлена: {conv_id}")

    except Exception as e:
        # Логируем ошибку, но не прерываем выполнение
        logger.error(f"❌ Ошибка при записи в Google Sheets: {e}")