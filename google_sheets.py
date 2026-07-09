import gspread
from google.oauth2.service_account import Credentials
import os
import logging
import json

logger = logging.getLogger(__name__)

# Чтение переменных окружения
SHEET_ID = os.environ.get('GOOGLE_SHEET_ID', '')
ENABLED = os.environ.get('ENABLE_GOOGLE_SHEETS', 'false').lower() == 'true'
USE_CHAT_LINK = os.environ.get('USE_CHAT_LINK', 'true').lower() == 'true'

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

def get_credentials():
    """Получает credentials из переменной GOOGLE_CREDENTIALS_JSON или из файла (локально)."""
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    if creds_json:
        try:
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except Exception as e:
            logger.error(f"Ошибка парсинга GOOGLE_CREDENTIALS_JSON: {e}")
            raise
    else:
        # fallback для локальной разработки (если есть файл)
        CREDENTIALS_FILE = os.environ.get('GOOGLE_CREDENTIALS_FILE', 'credentials.json')
        return Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)

def get_or_create_worksheet(client, sheet_id, sheet_name):
    """Возвращает лист по имени, создавая его, если не существует."""
    spreadsheet = client.open_by_key(sheet_id)
    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        logger.info(f"📄 Найден лист '{sheet_name}'")
        return worksheet
    except gspread.WorksheetNotFound:
        # Создаём лист с указанным именем
        worksheet = spreadsheet.add_worksheet(title=sheet_name, rows=100, cols=20)
        logger.info(f"📄 Создан новый лист '{sheet_name}'")
        # Добавляем заголовки (опционально)
        headers = ['operator_name', 'conversation_id', 'closed_at_utc', 'queue_name', 'timestamp']
        worksheet.append_row(headers)
        return worksheet

def append_record(record_data):
    creds_json = os.environ.get('GOOGLE_CREDENTIALS_JSON')
logger.info(f"Длина JSON-ключа: {len(creds_json) if creds_json else 0}")
if creds_json:
    try:
        import json
        json.loads(creds_json)
        logger.info("JSON валидный")
    except Exception as e:
        logger.error(f"JSON невалидный: {e}")
    logger.info("🔍 append_record вызвана")
    """Добавляет строку в Google Таблицу, если функция включена."""
    if not ENABLED:
        logger.info("Запись в Google Sheets отключена (ENABLED=false)")
        return

    if not SHEET_ID:
        logger.warning("Google Sheet ID не задан, пропускаем запись")
        return

    try:
        creds = get_credentials()
        client = gspread.authorize(creds)

        # Используем лист с именем "logs", создаём если нет
        sheet_name = os.environ.get('GOOGLE_SHEET_NAME', 'logs')
        sheet = get_or_create_worksheet(client, SHEET_ID, sheet_name)

        # Формируем значение для conversation_id (ссылку или просто ID)
        conv_id = record_data.get('conversation_id', '')
        if USE_CHAT_LINK and conv_id:
            chat_value = f"https://chat.moneyman.ru/operator/chat/{conv_id}"
        else:
            chat_value = conv_id

        # Порядок колонок должен соответствовать заголовкам
        row = [
            record_data.get('operator_name', ''),
            chat_value,
            record_data.get('closed_at_utc', ''),
            record_data.get('queue_name', ''),
            record_data.get('timestamp', '')
        ]
        sheet.append_row(row)
        logger.info(f"✅ Запись в Google Sheets добавлена: {conv_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка при записи в Google Sheets: {e}")