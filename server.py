"""
Apple TV Remote — FastAPI + WebSockets 后端
提供:
  GET  /                  -> SPA index.html
  WS   /ws                -> 实时推送键盘状态与文本
  GET  /api/status        -> 连接状态
  POST /api/connect       -> 用已保存凭据连接设备
  POST /api/command       -> 发送遥控指令
  GET  /api/playing       -> 正在播放信息
  POST /api/scan          -> 扫描局域网设备
  POST /api/pair/start    -> 开始配对
  POST /api/pair/pin      -> 提交 PIN
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional, Any, List

import pyatv
from pyatv.const import Protocol, FeatureName
from pyatv.interface import PushListener, Keyboard
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# ──────────────────── 配置路径 ────────────────────
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
CONFIG_DIR = os.path.join(APPDATA, "AppleTVRemote")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            return json.load(open(CONFIG_FILE, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    json.dump(cfg, open(CONFIG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ──────────────────── WebSocket 管理 ────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # 异步广播消息给所有连入的网页
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


# ──────────────────── 全局状态 ────────────────────
_config: dict = load_config()
_atv: Optional[Any] = None
_pair_session: dict = {}
_pair_handler: Optional[Any] = None
_push_listener: Optional[Any] = None
_kb_listener: Optional[Any] = None


# ──────────────────── 协议监听器 ────────────────────
class AtvKeyboardListener(Keyboard):
    """单独监听键盘焦点的监听器 (pyatv 0.17.0)"""
    def focus_state_changed(self, focus_state):
        print(f"DEBUG - 键盘焦点变化: {focus_state}")
        # 推送给所有连入的 WebSocket
        asyncio.create_task(manager.broadcast({
            "type": "keyboard_status",
            "active": focus_state.is_focused,
            "display_name": getattr(focus_state, "display_name", "输入框")
        }))
        # 如果获得焦点，立即尝试同步一次当前已有文字
        if focus_state.is_focused and _atv and _atv.keyboard:
            async def sync_initial():
                await asyncio.sleep(0.5) # 等待电视端稳定
                try:
                    text = await _atv.keyboard.text_get()
                    await manager.broadcast({"type": "text_sync", "text": text})
                except: pass
            asyncio.create_task(sync_initial())

    def text_was_updated(self, text):
        print(f"DEBUG - 电视端文字更新: {text}")
        asyncio.create_task(manager.broadcast({
            "type": "text_sync",
            "text": text
        }))

class AtvPushListener(PushListener):
    """通用推送监听 (播放状态等)"""
    def playstatus_update(self, updater, playstatus):
        asyncio.create_task(manager.broadcast({
            "type": "playing_update",
            "title": playstatus.title,
            "state": str(playstatus.device_state).split('.')[-1]
        }))

    def playstatus_error(self, updater, exception):
        print(f"DEBUG - 推送错误: {exception}")


# 遥控指令映射
ACTION_MAP = {
    "up":           lambda rc: rc.up(),
    "down":         lambda rc: rc.down(),
    "left":         lambda rc: rc.left(),
    "right":        lambda rc: rc.right(),
    "select":       lambda rc: rc.select(),
    "menu":         lambda rc: rc.menu(),
    "home":         lambda rc: rc.home(),
    "back":         lambda rc: rc.menu(),
    "play_pause":   lambda rc: rc.play_pause(),
    "play":         lambda rc: rc.play(),
    "pause":        lambda rc: rc.pause(),
    "volume_up":    lambda rc: rc.volume_up(),
    "volume_down":  lambda rc: rc.volume_down(),
    "power":        lambda rc: rc.home_hold(),
    "siri":         lambda rc: rc.top_menu(),
}


# ──────────────────── ATV 连接 ────────────────────
async def connect_device():
    global _atv, _push_listener, _kb_listener
    if _atv:
        try: _atv.close()
        except: pass
        _atv = None

    device_id = _config.get("device_id")
    if not device_id: return False

    try:
        loop = asyncio.get_event_loop()
        results = await pyatv.scan(loop, identifier=device_id, timeout=5)
        if not results: return False
        
        conf = results[0]
        # 注入凭据
        for proto in [Protocol.MRP, Protocol.AirPlay, Protocol.DMAP, Protocol.Companion]:
            creds = _config.get(f"{proto.name.lower()}_credentials")
            if creds:
                svc = conf.get_service(proto)
                if svc: svc.credentials = creds
        
        _atv = await pyatv.connect(conf, loop)
        
        # 1. 注册通用监听
        _push_listener = AtvPushListener()
        _atv.push_updater.listener = _push_listener
        _atv.push_updater.start()
        
        # 2. 注册键盘专用监听 (核心)
        if _atv.keyboard:
            _kb_listener = AtvKeyboardListener()
            _atv.keyboard.listener = _kb_listener
            print("DEBUG - 键盘监听器已注册")
            
        return True
    except Exception as e:
        print(f"连接失败: {e}")
        return False


# ──────────────────── App 工厂 ────────────────────
def create_app(static_dir: str) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if _config.get("device_id"):
            asyncio.create_task(connect_device())
        yield
        if _atv: _atv.close()

    app = FastAPI(title="Apple TV Remote", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    
    # ── WebSocket 终端 ──
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                # 处理从网页发回的打字请求
                if message.get("type") == "set_text" and _atv and _atv.keyboard:
                    text = message.get("text", "")
                    try:
                        # 尝试多种输入方式提升兼容性
                        try:
                            await _atv.keyboard.text_set(text)
                        except:
                            await _atv.keyboard.text_append(text)
                    except Exception as e:
                        print(f"DEBUG - 同步文本失败: {e}")
                
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as e:
            print(f"DEBUG - WS 异常: {e}")
            manager.disconnect(websocket)

    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/api/status")
    async def status():
        return {
            "connected": _atv is not None,
            "device_name": _config.get("device_name", ""),
            "device_id": _config.get("device_id", ""),
            "keyboard_ready": _atv is not None and _atv.keyboard is not None
        }

    @app.post("/api/connect")
    async def connect():
        ok = await connect_device()
        return {"ok": ok}

    class CommandBody(BaseModel):
        action: str

    @app.post("/api/command")
    async def command(body: CommandBody):
        global _atv
        action = body.action.lower().strip()
        if action not in ACTION_MAP:
            raise HTTPException(400, "Unknown action")
        
        if _atv is None:
            if not await connect_device():
                raise HTTPException(503, "Device not connected")
        
        try:
            await ACTION_MAP[action](_atv.remote_control)
            return {"ok": True}
        except Exception as e:
            _atv = None
            raise HTTPException(500, str(e))

    @app.get("/api/playing")
    async def playing():
        if not _atv: return {"state": "Idle"}
        try:
            p = await _atv.metadata.playing()
            return {
                "title": p.title or "Unknown",
                "artist": p.artist or "",
                "state": str(p.device_state).split('.')[-1]
            }
        except:
            return {"state": "Unknown"}

    @app.post("/api/scan")
    async def scan():
        try:
            loop = asyncio.get_event_loop()
            devices = await pyatv.scan(loop, timeout=5)
            results = []
            for d in devices:
                results.append({
                    "name": d.name,
                    "id": d.identifier,
                    "address": str(d.address),
                    "services": [{"protocol": s.protocol.name} for s in d.services]
                })
            return {"devices": results}
        except Exception as e:
            raise HTTPException(500, str(e))

    class PairStart(BaseModel):
        device_id: str
        protocol: str = "MRP"

    @app.post("/api/pair/start")
    async def pair_start(body: PairStart):
        global _pair_handler, _pair_session
        loop = asyncio.get_event_loop()
        devices = await pyatv.scan(loop, identifier=body.device_id, timeout=5)
        if not devices: raise HTTPException(404, "Device not found")
        
        conf = devices[0]
        # 关键修正：如果支持 Companion，优先提示用户同时配对它
        proto = Protocol.MRP if body.protocol == "MRP" else Protocol.AirPlay
        if body.protocol == "Companion": proto = Protocol.Companion
        
        try:
            _pair_handler = await pyatv.pair(conf, proto, loop)
            await _pair_handler.begin()
            _pair_session = {
                "device_id": body.device_id,
                "protocol": body.protocol,
                "name": conf.name,
                "address": str(conf.address)
            }
            return {"ok": True, "needs_pin": _pair_handler.device_provides_pin}
        except Exception as e:
            raise HTTPException(500, str(e))

    @app.post("/api/pair/pin")
    async def pair_pin(body: dict):
        global _pair_handler, _config
        pin = body.get("pin")
        if not _pair_handler or not pin: raise HTTPException(400, "Invalid session")
        try:
            _pair_handler.pin(int(pin))
            await _pair_handler.finish()
            if _pair_handler.has_paired:
                creds = str(_pair_handler.service.credentials)
                proto_key = f"{_pair_session['protocol'].lower()}_credentials"
                _config.update({
                    "device_id": _pair_session["device_id"],
                    "device_name": _pair_session["name"],
                    "device_ip": _pair_session["address"],
                    proto_key: creds
                })
                save_config(_config)
                await _pair_handler.close()
                await connect_device()
                return {"ok": True}
            else:
                raise Exception("Pairing failed")
        except Exception as e:
            raise HTTPException(500, str(e))

    return app
