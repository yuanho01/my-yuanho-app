# -*- coding: utf-8 -*-
import os
import json
import time
import base64
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.utils import secure_filename

# 引入 LINE Bot 與 Google Gemini AI 所需的工具
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
from google import genai

app = Flask(__name__)

REPO_OWNER = 'yuanho01'
REPO_NAME = 'my-yuanho-app'

app.secret_key = 'your_secret_key_here'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
DATA_FILE = 'data.json'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 設定 LINE Bot 與 Gemini AI 密鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "您的LINE Token")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "您的LINE Secret")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Google Gemini AI 客戶端
ai_client = genai.Client()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def fetch_github_file_sha():
    github_token = os.environ.get('GITHUB_TOKEN')
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{DATA_FILE}"
    headers = {'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get('sha')
        return None
    except Exception:
        return None


def sync_data_to_github(data_content):
    github_token = os.environ.get('GITHUB_TOKEN')
    json_string = json.dumps(data_content, ensure_ascii=False, indent=4)
    base64_content = base64.b64encode(json_string.encode('utf-8')).decode('utf-8')
    file_sha = fetch_github_file_sha()
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{DATA_FILE}"
    headers = {'Authorization': f'token {github_token}', 'Accept': 'application/vnd.github.v3+json'}
    payload = {"message": "Auto-backup", "content": base64_content, "branch": "main"}
    if file_sha:
        payload["sha"] = file_sha
    try:
        requests.put(url, headers=headers, json=payload)
    except Exception:
        pass


def load_data():
    default_data = {
        "contact": {"region": "雲、嘉、南到府服務", "phone": "0988-562-288", "line_id": "@403wemjq"},
        "news": [], "products": [], "shop_items": [], "services": [], "users": {}, "orders": []
    }
    if not os.path.exists(DATA_FILE):
        return default_data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for key in default_data:
            if key not in data:
                data[key] = default_data[key]
        return data
    except Exception:
        return default_data


def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    sync_data_to_github(data)


@app.route('/')
def index():
    data = load_data()
    cart = session.get('cart', {})
    subtotal = 0
    cart_items = []

    for item_id_str, quantity in cart.items():
        item_id = int(item_id_str)
        product = next((p for p in data.get('shop_items', []) if p['id'] == item_id), None)
        if product:
            try:
                price_val = int(str(product.get('price', '0')).replace('NT$', '').replace(',', '').strip())
            except ValueError:
                price_val = 0
            item_total = price_val * quantity
            subtotal += item_total
            cart_items.append({"id": product['id'], "title": product['title'], "price": price_val, "quantity": quantity,
                               "total": item_total, "image": product.get('image')})

    is_logged_in = session.get('logged_in_user') is not None
    logged_in_user = session.get('logged_in_user', '')
    discount_total = int(subtotal * 0.9) if is_logged_in else subtotal

    all_user_orders = [o for o in data.get('orders', []) if o.get('username') == logged_in_user] if is_logged_in else []
    user_orders = [o for o in all_user_orders if o.get('status', 'active') in ['active', 'processing', 'shipped']]
    user_history_orders = [o for o in all_user_orders if o.get('status') == 'completed']

    return render_template('index.html', news_list=data.get('news', []), products=data.get('products', []),
                           shop_items=data.get('shop_items', []), services=data.get('services', []),
                           contact=data.get('contact', {}), cart_items=cart_items, subtotal=subtotal,
                           discount_total=discount_total, is_logged_in=is_logged_in,
                           user_orders=user_orders, user_history_orders=user_history_orders)


@app.route('/checkout', methods=['POST'])
def checkout():
    cart = session.get('cart', {})
    if not cart:
        flash('購物車是空的！', 'warning')
        return redirect(url_for('index'))

    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()

    if not name or not phone or not address:
        flash('請完整填寫收件人姓名、電話與地址！', 'danger')
        return redirect(url_for('index'))

    data = load_data()
    subtotal = 0
    order_items = []
    for item_id_str, quantity in cart.items():
        item_id = int(item_id_str)
        product = next((p for p in data.get('shop_items', []) if p['id'] == item_id), None)
        if product:
            try:
                price_val = int(str(product.get('price', '0')).replace('NT$', '').replace(',', '').strip())
            except ValueError:
                price_val = 0
            item_total = price_val * quantity
            subtotal += item_total
            order_items.append(
                {"title": product['title'], "price": price_val, "quantity": quantity, "total": item_total})

    is_logged_in = session.get('logged_in_user') is not None
    username = session.get('logged_in_user', '訪客')
    final_total = int(subtotal * 0.9) if is_logged_in else subtotal

    order_id_str = str(int(time.time()))
    order_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    new_order = {
        "order_id": order_id_str,
        "username": username,
        "name": name,
        "phone": phone,
        "address": address,
        "items": order_items,
        "subtotal": subtotal,
        "final_total": final_total,
        "is_member_discount": is_logged_in,
        "time": order_time_str,
        "status": "processing"
    }
    if 'orders' not in data:
        data['orders'] = []
    data['orders'].insert(0, new_order)

    save_data(data)
    notify_admin(new_order)
    session.pop('cart', None)

    flash('訂單已成功送出！我們將盡快與您聯繫。', 'success')
    return redirect(url_for('index'))


@app.route('/user_complete_order/<order_id>', methods=['POST'])
def user_complete_order(order_id):
    if not session.get('logged_in_user'):
        flash('請先登入！', 'danger')
        return redirect(url_for('user_login'))

    logged_in_user = session.get('logged_in_user')
    data = load_data()

    for order in data.get('orders', []):
        if order.get('order_id') == order_id and order.get('username') == logged_in_user:
            order['status'] = 'completed'
            break

    save_data(data)
    flash('已確認收到貨！該訂單已移至歷史紀錄。', 'success')
    return redirect(url_for('index'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        data = load_data()
        if username in data['users']:
            flash('帳號已被註冊！', 'danger')
            return redirect(url_for('register'))
        data['users'][username] = password
        save_data(data)
        flash('註冊成功！', 'success')
        return redirect(url_for('user_login'))
    return render_template('register.html')


@app.route('/user_login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        data = load_data()
        if username in data.get('users', {}) and data['users'][username] == password:
            session['logged_in_user'] = username
            flash('登入成功！', 'success')
            return redirect(url_for('index'))
        else:
            flash('帳號或密碼錯誤！', 'danger')
    return render_template('user_login.html')


@app.route('/user_logout')
def user_logout():
    session.pop('logged_in_user', None)
    return redirect(url_for('index'))


@app.route('/add_to_cart/<int:item_id>')
def add_to_cart(item_id):
    cart = session.get('cart', {})
    cart[str(item_id)] = cart.get(str(item_id), 0) + 1
    session['cart'] = cart
    return redirect(url_for('index'))


@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == 'admin123':
            session['logged_in'] = True
            return redirect(url_for('admin'))
        else:
            flash('密碼錯誤!', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/admin')
def admin():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = load_data()
    return render_template('admin.html', news_list=data.get('news', []), products=data.get('products', []),
                           shop_items=data.get('shop_items', []), services=data.get('services', []),
                           contact=data.get('contact', {}), orders=data.get('orders', []))


@app.route('/admin/complete_order/<order_id>', methods=['POST'])
def complete_order(order_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    data = load_data()
    for order in data.get('orders', []):
        if order.get('order_id') == order_id:
            order['status'] = 'shipped'
            break
    save_data(data)
    flash('該筆訂單已標記為【已出貨】，等待買家確認收貨！', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/update_contact', methods=['POST'])
def update_contact():
    if not session.get('logged_in'): return redirect(url_for('login'))
    data = load_data()
    data['contact'] = {'region': request.form.get('region', '').strip(), 'phone': request.form.get('phone', '').strip(),
                       'line_id': request.form.get('line_id', '').strip()}
    save_data(data)
    return redirect(url_for('admin'))


def handle_add_item(key):
    title = request.form.get('title')
    description = request.form.get('description', '')
    price = request.form.get('price', '')
    link_url = request.form.get('link_url', '')
    file = request.files.get('image')
    image_filename = None
    if file and allowed_file(file.filename):
        image_filename = f"{int(time.time())}_{secure_filename(file.filename)}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
    data = load_data()
    items = data.get(key, [])
    new_id = items[0]['id'] + 1 if items else 1
    items.insert(0, {'id': new_id, 'title': title, 'description': description, 'price': price, 'link_url': link_url,
                     'image': image_filename})
    data[key] = items
    save_data(data)


def handle_delete_item(key, item_id):
    data = load_data()
    data[key] = [item for item in data.get(key, []) if item.get('id') != item_id]
    save_data(data)


@app.route('/admin/add_news', methods=['POST'])
def add_news():
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_add_item('news')
    return redirect(url_for('admin'))


@app.route('/admin/delete_news/<int:item_id>', methods=['POST'])
def delete_news(item_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_delete_item('news', item_id)
    return redirect(url_for('admin'))


@app.route('/admin/add_product', methods=['POST'])
def add_product():
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_add_item('products')
    return redirect(url_for('admin'))


@app.route('/admin/delete_product/<int:item_id>', methods=['POST'])
def delete_product(item_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_delete_item('products', item_id)
    return redirect(url_for('admin'))


@app.route('/admin/add_shop', methods=['POST'])
def add_shop():
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_add_item('shop_items')
    return redirect(url_for('admin'))


@app.route('/admin/delete_shop/<int:item_id>', methods=['POST'])
def delete_shop(item_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_delete_item('shop_items', item_id)
    return redirect(url_for('admin'))


@app.route('/admin/add_service', methods=['POST'])
def add_service():
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_add_item('services')
    return redirect(url_for('admin'))


@app.route('/admin/delete_service/<int:item_id>', methods=['POST'])
def delete_service(item_id):
    if not session.get('logged_in'): return redirect(url_for('login'))
    handle_delete_item('services', item_id)
    return redirect(url_for('admin'))


# ==========================================
# 管理員新訂單自動推播小工具
# ==========================================
def notify_admin(order):
    admin_id = os.environ.get("ADMIN_LINE_USER_ID")
    if not admin_id:
        return

    msg = (
        f"🚨 【新訂單通知】\n"
        f"------------------------------\n"
        f"訂單編號：{order.get('order_id')}\n"
        f"客戶姓名：{order.get('name')}\n"
        f"連絡電話：{order.get('phone')}\n"
        f"服務地址：{order.get('address')}\n"
        f"------------------------------\n"
        f"請盡快為客戶安排服務或出貨！"
    )
    try:
        line_bot_api.push_message(admin_id, TextSendMessage(text=msg))
    except Exception as e:
        print(f"推播失敗: {e}")


# ==========================================
# LINE Bot 接收與 Gemini AI 智慧回覆路由
# ==========================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    user_id = event.source.user_id

    data = load_data()
    if "users" not in data:
        data["users"] = {}
    if user_id not in data["users"]:
        data["users"][user_id] = {"step": "idle", "name": "", "phone": "", "address": ""}

    user_state = data["users"][user_id]

    # 1. 偵測是否想找真人客服
    if any(keyword in user_text for keyword in ["真人", "老闆", "人工", "電話", "專人"]):
        reply_text = "📞 您好！您可以直接撥打建安工作室服務專線：0988-562-288，將由專人為您服務！或者您也可以直接在圖文選單中按一下「線上客服」，我們將為您登記聯絡資訊，安排專人為您服務喔！"

    # 2. 觸發機器人登記流程（支援多種常見關鍵字，不包含單獨的「你好」）
    elif any(keyword in user_text for keyword in ["你好我要找客服", "你好！我要找客服", "我要找客服", "找客服"]):
        reply_text = "您好！我是建安工作室的小秘書客服，在這裡為您服務。\n請先輸入您的【聯絡人姓名】："
        user_state["step"] = "get_name"
        user_state["name"] = ""
        user_state["phone"] = ""
        user_state["address"] = ""

    # 3. 登記步驟：姓名
    elif user_state["step"] == "get_name":
        user_state["name"] = user_text
        reply_text = f"收到，您的姓名是【{user_text}】。\n接下來，請輸入您的【連絡電話】："
        user_state["step"] = "get_phone"

    # 4. 登記步驟：電話
    elif user_state["step"] == "get_phone":
        if not any(char.isdigit() for char in user_text):
            reply_text = "⚠️ 電話號碼格式怪怪的喔！請輸入正確的【連絡電話】："
        else:
            user_state["phone"] = user_text
            reply_text = "太好了！最後，請輸入您的【收件/服務地址】："
            user_state["step"] = "get_address"

    # 5. 登記步驟：地址並建立訂單
    elif user_state["step"] == "get_address":
        if len(user_text) < 3 or user_text in ["為什麼", "不知道", "測試"]:
            reply_text = "⚠️ 請輸入詳細的【收件/服務地址】（包含鄉鎮市區與路名），以便我們安排服務："
        else:
            user_state["address"] = user_text
            user_state["step"] = "completed"

            order_id_str = str(int(time.time()))
            order_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            new_order = {
                "order_id": order_id_str,
                "username": user_id,
                "name": user_state["name"],
                "phone": user_state["phone"],
                "address": user_state["address"],
                "items": [],
                "subtotal": 0,
                "final_total": 0,
                "is_member_discount": False,
                "time": order_time_str,
                "status": "processing"
            }
            if "orders" not in data:
                data["orders"] = []
            data["orders"].insert(0, new_order)
            save_data(data)

            # 🚀 觸發管理員自動推播通知
            notify_admin(new_order)

            reply_text = f"✅ 訂單已成功建立！\n------------------------------\n姓名：{user_state['name']}\n電話：{user_state['phone']}\n地址：{user_state['address']}\n訂單編號：{order_id_str}\n------------------------------\n我們將盡快與您聯絡！"
            user_state["step"] = "idle"

    # 6. 一般閒聊或問問題交給 Gemini AI (已更新為最新 gemini-3.6-flash 模型)
    else:
        try:
            prompt = (
                "你是一個專業、親切且有禮貌的在地工作室小秘書，專門服務雲、嘉、南地區的客戶。"
                "工作室的主要業務包含：二手桌上型電腦銷售、監視器安裝維修、RO濾水器安裝與換濾芯保養。"
                "請根據客戶的問題給予溫暖、專業且簡短的回答。如果客戶想買東西或預約服務，請引導他們直接在圖文選單中按一下「線上客服」，或輸入「我要找客服」來登記聯絡資訊。"
                f"客戶的問題是：{user_text}"
            )
            response = ai_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt
            )
            reply_text = response.text
        except Exception as e:
            print(f"Gemini API Error: {e}")
            reply_text = "您好！關於您的問題，您可以直接撥打我們的服務專線 0988-562-288，或是直接在圖文選單中按一下「線上客服」，我們將為您登記聯絡資訊，安排專人為您服務喔！"

    save_data(data)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)