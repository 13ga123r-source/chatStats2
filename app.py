import os
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask, request, render_template_string

app = Flask(__name__)

DB_PATH = os.environ.get('DB_PATH', 'stats.db')
PORT = int(os.environ.get('PORT', 5000))
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

CHANNEL_ORDER = [
    "Support PLZ: Chat",
    "Support MM: Email",
    "Support MM: Chat",
    "Collection MM: Chat",
    "Collection PLZ: Chat"
]

def migrate_db():
    """Создаёт таблицу с колонкой queue_name, если её нет"""
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='closed_chats'")
        if not cursor.fetchone():
            conn.execute('''
                CREATE TABLE closed_chats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operator_name TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    closed_at_utc TEXT NOT NULL,
                    queue_name TEXT
                )
            ''')
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_at ON closed_chats(closed_at_utc)")
            print("✅ Таблица closed_chats создана")
            return

        # Проверяем наличие колонки queue_name
        columns = conn.execute("PRAGMA table_info(closed_chats)").fetchall()
        has_queue = any(col[1] == 'queue_name' for col in columns)
        if not has_queue:
            conn.execute("ALTER TABLE closed_chats ADD COLUMN queue_name TEXT")
            print("✅ Добавлена колонка queue_name")

def init_db():
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute('PRAGMA journal_mode = WAL')
    migrate_db()

init_db()

def moscow_date_from_utc(utc_iso_str: str):
    """Возвращает дату в Москве в формате DD.MM.YYYY"""
    cleaned = utc_iso_str.replace('Z', '+00:00')
    if '+' not in cleaned:
        cleaned += '+00:00'
    dt_utc = datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    moscow_dt = dt_utc.astimezone(MOSCOW_TZ)
    return moscow_dt.strftime('%d.%m.%Y')

def get_unique_dates():
    """Возвращает список уникальных дат (МСК) из БД, отсортированных по убыванию"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT closed_at_utc FROM closed_chats").fetchall()
    dates_set = set()
    for (closed_utc,) in rows:
        try:
            d = moscow_date_from_utc(closed_utc)
            dates_set.add(d)
        except:
            pass
    # Сортировка по дате (от новых к старым)
    sorted_dates = sorted(dates_set, key=lambda x: datetime.strptime(x, '%d.%m.%Y'), reverse=True)
    return sorted_dates

def get_stats_for_date(date_str):
    """Возвращает статистику за указанную дату (DD.MM.YYYY) в виде словаря:
       { queue_name: { operator_name: count } }
    """
    # Преобразуем DD.MM.YYYY в YYYY-MM-DD для SQL
    try:
        d = datetime.strptime(date_str, '%d.%m.%Y')
        sql_date = d.strftime('%Y-%m-%d')
    except:
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute('''
            SELECT operator_name, queue_name
            FROM closed_chats
            WHERE date(closed_at_utc, '+3 hours') = ?
        ''', (sql_date,)).fetchall()
    groups = {}
    for operator, queue in rows:
        q = queue if queue else 'Без канала'
        if q not in groups:
            groups[q] = {}
        groups[q][operator] = groups[q].get(operator, 0) + 1
    return groups

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return ("", 200)
        event = payload.get('event')
        if event != 'chat.closed':
            return ("", 200)
        data = payload.get('data')
        if not data:
            return ("", 200)

        queue = data.get('queue') or {}
        queue_name = queue.get('name', '')
        operator = data.get('operator') or {}
        operator_name = operator.get('name')
        conversation = data.get('conversation') or {}
        conv_id = conversation.get('id')
        closed_at = conversation.get('closed_at')

        if not operator_name or not conv_id or not closed_at:
            print(f"⚠️ Пропущен: name={operator_name}, id={conv_id}, closed_at={closed_at}")
            return ("", 200)

        with sqlite3.connect(DB_PATH, timeout=10) as conn:
            conn.execute('''
                INSERT INTO closed_chats (operator_name, conversation_id, closed_at_utc, queue_name)
                VALUES (?, ?, ?, ?)
            ''', (operator_name, conv_id, closed_at, queue_name))
            print(f"✅ Сохранён {operator_name} - {conv_id} (канал: {queue_name or 'не указан'})")
        return ("", 200)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return ("", 200)

@app.route('/stats')
def stats():
    # Получаем параметр date, если не задан – сегодня
    date_param = request.args.get('date')
    if date_param:
        try:
            datetime.strptime(date_param, '%d.%m.%Y')
            selected_date = date_param
        except:
            selected_date = datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y')
    else:
        selected_date = datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y')

    # Статистика за выбранную дату
    groups = get_stats_for_date(selected_date)
    # Уникальные даты для кнопок
    all_dates = get_unique_dates()
    # Сортируем и выбираем топ-10 последних (чтобы не перегружать интерфейс)
    all_dates = all_dates[:15]  # не более 15 кнопок

    # HTML-шаблон
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Статистика закрытых чатов</title>
        <style>
            body { font-family: sans-serif; margin: 20px; font-size: 14px; }
            .dates { margin-bottom: 20px; display: flex; flex-wrap: wrap; gap: 8px; }
            .date-button {
                display: inline-block;
                padding: 6px 12px;
                background-color: #f2f2f2;
                border: 1px solid #ccc;
                border-radius: 4px;
                text-decoration: none;
                color: #333;
                cursor: pointer;
            }
            .date-button.active {
                background-color: #4CAF50;
                color: white;
                border-color: #4CAF50;
            }
            .date-button:hover {
                background-color: #ddd;
            }
            .channel { margin-bottom: 30px; }
            .channel h3 { margin-bottom: 10px; color: #2c3e50; }
            table {
                border-collapse: collapse;
                width: 50%;
                margin-bottom: 20px;
            }
            th, td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: left;
            }
            th { background-color: #f2f2f2; }
            .count { font-weight: bold; }
            .no-data { color: #888; font-style: italic; }
        </style>
    </head>
    <body>
        <h2>📊 Статистика закрытых чатов за {{ selected_date }}</h2>

        <div class="dates">
            <a href="/stats" class="date-button {% if selected_date == today %}active{% endif %}">Сегодня</a>
            {% for d in all_dates %}
                <a href="/stats?date={{ d }}" class="date-button {% if d == selected_date %}active{% endif %}">{{ d }}</a>
            {% endfor %}
        </div>

        {% set has_data = false %}
        {% for channel in channel_order %}
            {% if groups[channel] %}
                {% set has_data = true %}
                <div class="channel">
                    <h3>{{ channel }}</h3>
                    <table>
                        <tr><th>#</th><th>Оператор</th><th>Кол-во</th></tr>
                        {% for op, count in groups[channel].items()|sort(attribute='1', reverse=true) %}
                            <tr>
                                <td>{{ loop.index }}</td>
                                <td>{{ op }}</td>
                                <td class="count">{{ count }}</td>
                            </tr>
                        {% endfor %}
                    </table>
                </div>
            {% endif %}
        {% endfor %}

        {% if groups['Без канала'] %}
            {% set has_data = true %}
            <div class="channel">
                <h3>Без канала</h3>
                <table>
                    <tr><th>#</th><th>Оператор</th><th>Кол-во</th></tr>
                    {% for op, count in groups['Без канала'].items()|sort(attribute='1', reverse=true) %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td>{{ op }}</td>
                            <td class="count">{{ count }}</td>
                        </tr>
                    {% endfor %}
                </table>
            </div>
        {% endif %}

        {% if not has_data %}
            <p class="no-data">Нет данных за выбранную дату.</p>
        {% endif %}
    </body>
    </html>
    '''

    from flask import render_template_string
    return render_template_string(
        html,
        selected_date=selected_date,
        today=datetime.now(MOSCOW_TZ).strftime('%d.%m.%Y'),
        all_dates=all_dates,
        groups=groups,
        channel_order=CHANNEL_ORDER
    )

@app.route('/debug')
def debug():
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT id, operator_name, conversation_id, closed_at_utc, queue_name FROM closed_chats ORDER BY id DESC LIMIT 50").fetchall()
    if not rows:
        return "Таблица пуста"
    result = "<h3>Последние 50 записей</h3><table border='1'>"
    result += "<tr><th>ID</th><th>Оператор</th><th>Conversation ID</th><th>closed_at (UTC)</th><th>queue_name</th></tr>"
    for row in rows:
        result += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td><td>{row[4]}</td></tr>"
    result += "</table>"
    return result

@app.route('/health')
def health():
    return "OK"

if __name__ == '__main__':
    print(f"🚀 Сервер запущен на порту {PORT}")
    app.run(host='0.0.0.0', port=PORT, threaded=True)