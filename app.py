# -*- coding: utf-8 -*-
import os
import json
import time
import base64
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)

REPO_OWNER = 'yuanho01'
REPO_NAME = 'my-yuanho-app'

app.secret_key = 'your_secret_key_here'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
DATA_FILE = 'data.json'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

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

    all_user_orders = [o for o in data.get('orders', []) if o.get('username') == logged_in_user] if is_logged_in else[]
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
    session.pop('cart', None)

    # 透過 LINE Messaging API 發送即時訂單通知
    try:
        line_token = "DaL1aZe9xmFwD5cn7lpswPIpwGFyh8F1rG0VYn8GbBHuOdWTKWTpPOa8umgmy97dF6aVxm/DIpwGp5KQ9wEBsVO9tTrgKqSPeKYM+wXx/qO0iBJ/WagNnrjiLq16n76AXjFiQlSrHmnQDa5SOEjufQdB04t89/1O/w1cDnyilFU="
        user_id = "Udf5ee6924620bc596fe3a3273adbc5ea"

        if user_id:
            url = "https://api.line.me/v2/bot/message/push"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {line_token}"
            }
            message_text = f"【雲嘉南二手電腦】新訂單通知！\n" \
                           f"------------------------------\n" \
                           f"訂單編號：{order_id_str}\n" \
                           f"下單會員：{username}\n" \
                           f"收件姓名：{name}\n" \
                           f"連絡電話：{phone}\n" \
                           f"收件地址：{address}\n" \
                           f"------------------------------\n" \
                           f"總金額：NT$ {final_total}\n" \
                           f"下單時間：{order_time_str}\n" \
                           f"請至網站後台查看完整明細！"
            payload = {
                "to": user_id,
                "messages": [{"type": "text", "text": message_text}]
            }
            requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print(f"LINE 通知發送失敗: {e}")

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


# 💡 呼叫 Google Gemini API 產生智慧回覆
def get_gemini_response(user_message):
    try:
        # 將模型名稱改為 gemini-1.5-flash 或 gemini-pro，確保 v1beta 抓得到
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}

        system_prompt = (
            "【系統角色與規範】\n"
            "你是一個專業、親切且有禮貌的在地店家客服助理，店家老闆是建安大哥。 \n"
            "我們的業務範圍與服務項目如下：\n"
            "1. 服務地區嚴格限定在：【雲林、嘉義、台南】地區。如果客戶詢問其他縣市，請客氣告知目前未提供該地區服務。\n"
            "2. 我們提供到府維修、安裝與服務，出發點是【台南新營】。\n"
            "3. 車馬費計算規則（依距離遠近從新營出發）：例如下營約 200 元、水上約 400 元，較遠或鄰近地區請根據新營出發的距離合理估算車馬費，並主動詢問客戶是否能接受。\n"
            "4. 核心產品與服務：二手電腦、RO 淨水器、監視器安裝與各項到府技術服務。\n"
            "5. 請用繁體中文回覆，語氣要親切、像真人老闆或店長在跟客人對話一樣。\n\n"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": system_prompt + "客戶詢問：" + user_message}]
                }
            ]
        }

        response = requests.post(url, headers=headers, json=payload, timeout=10)
        res_json = response.json()
        print("Gemini 回應 JSON:", res_json)

        # 正常抓取 AI 回答
        if 'candidates' in res_json and len(res_json['candidates']) > 0:
            return res_json['candidates'][0]['content']['parts'][0]['text']
        else:
            # 如果還是有誤，把錯誤訊息印出來當作回覆
            err_msg = res_json.get('error', {}).get('message', '未知錯誤')
            return f"【AI連線提示】目前模型回應異常：{err_msg}"

    except Exception as e:
        print(f"Gemini API 呼叫錯誤: {e}")
        return f"【系統錯誤】{e}"