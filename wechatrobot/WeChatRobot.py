from typing import Callable, Dict, Any, Optional
from collections import deque
import threading
import logging
import requests
import os
import time

from .Api import Api
from .Bus import EventBus

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

Bus = EventBus()


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid integer env %s=%s, fallback=%s", name, value, default)
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        logging.warning("Invalid float env %s=%s, fallback=%s", name, value, default)
        return default


class WeChatRobot:
    BASE_PATH = "C:\\Users\\user\\My Documents\\WeChat Files"

    def __init__(self , ip : str = "0.0.0.0" , port : int = 23456):
        self.ip = ip
        self.port = port
        self.api = Api()

        self.bridge_api_base = os.environ.get("WECHATROBOT_BRIDGE_API_BASE", "http://127.0.0.1:19088").rstrip("/")
        self.pull_wait_ms = _env_int("WECHATROBOT_PULL_WAIT_MS", 15000)
        self.pull_batch_size = _env_int("WECHATROBOT_PULL_BATCH_SIZE", 50)
        self.retry_max_attempts = max(0, _env_int("WECHATROBOT_DISPATCH_RETRY_TIMES", 3))
        self.retry_base_seconds = max(0.1, _env_float("WECHATROBOT_DISPATCH_RETRY_BASE_SECONDS", 2.0))
        self._retry_queue = deque()
        self._login_state: Optional[bool] = None

    def on(self, *event_type: str) -> Callable:
        def deco(func: Callable) -> Callable:
            for _type in event_type:
                Bus.subscribe(_type, func)
            return deco
        return deco

    def _receive_callback(self, msg: Dict[str, Any]) -> None:
        type_dict = {
            0: 'eventnotify',
            1: 'text',
            3: 'image',
            9: 'scancashmoney',
            34: 'voice',
            35: 'qqmail',
            37: 'friendrequest',
            42: 'card',
            43: 'video',
            47: 'animatedsticker',
            48: 'location',
            49: 'share',
            50: 'voip',
            51: 'phone',
            106: 'sysnotify',
            1009: 'eventnotify',
            1010: 'eventnotify',
            2000: 'transfer',
            2001: 'redpacket',
            2002: 'miniprogram',
            2003: 'groupinvite',
            2004: 'file',
            2005: 'revokemsg',
            2006: 'groupannouncement',
            10000: 'sysmsg',
            10002: 'other'
        }

        msg['type'] = type_dict.get(msg['type'], 'unhandled' + str(msg['type']))

        if msg["type"] == "friendrequest":
            Bus.emit("frdver_msg", msg)
        elif msg["type"] == "card":
            Bus.emit("card_msg", msg)
        elif '<sysmsg type="revokemsg">' in msg["message"]:
            Bus.emit("revoke_msg", msg)
        elif "微信转账" in msg["message"] and "<paysubtype>1</paysubtype>" in msg["message"]:
            Bus.emit("transfer_msg", msg)
        elif 1 == msg["isSendMsg"]:
            if 1 == msg["isSendByPhone"]:
                Bus.emit("self_msg", msg)
            else:
                Bus.emit("sent_msg", msg)
        elif "chatroom" in msg["sender"]:
            Bus.emit("group_msg", msg)
        else:
            Bus.emit("friend_msg", msg)

    def _pull_once(self) -> bool:
        try:
            r = requests.post(
                f"{self.bridge_api_base}/v1/messages/pull",
                json={
                    "max_items": self.pull_batch_size,
                    "wait_ms": self.pull_wait_ms,
                },
                timeout=(3, self.pull_wait_ms / 1000 + 5),
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            self.api.invalidate_db_handles()
            logging.warning("Bridge pull failed: %s", e)
            return False

        for msg in payload.get("messages", []):
            self._dispatch_with_retry(msg)

        return True

    def _native_logged_in(self) -> bool:
        try:
            data = self.api.GetSelfInfo().get("data")
            ready = isinstance(data, dict) and isinstance(data.get("wxId"), str)
        except Exception:
            ready = False
        if ready != self._login_state:
            self._login_state = ready
            if ready:
                logging.info("Native WeChat login state changed: ready=True")
            else:
                logging.warning("Native WeChat login state changed: ready=False")
        return ready

    def _dispatch_with_retry(self, msg: Dict[str, Any], attempts: int = 0) -> None:
        try:
            self._receive_callback(msg)
            return
        except Exception as e:
            self.api.invalidate_db_handles()
            next_attempts = attempts + 1
            if not self._native_logged_in():
                delay = min(60.0, self.retry_base_seconds * (2 ** min(next_attempts, 5)))
                due_at = time.monotonic() + delay
                self._retry_queue.append((msg, next_attempts, due_at))
                logging.warning(
                    "Bridge message dispatch deferred until login, msgid=%s retry_in=%.1fs: %s",
                    msg.get("msgid"), delay, e,
                )
                return
            if self.retry_max_attempts <= 0 or next_attempts > self.retry_max_attempts:
                logging.error(
                    "Bridge message dispatch failed permanently, dropping msgid=%s attempts=%s: %s",
                    msg.get("msgid"), next_attempts, e,
                )
                return
            delay = self.retry_base_seconds * (2 ** (next_attempts - 1))
            due_at = time.monotonic() + delay
            self._retry_queue.append((msg, next_attempts, due_at))
            logging.warning(
                "Bridge message dispatch failed, retry %s/%s in %.1fs msgid=%s: %s",
                next_attempts, self.retry_max_attempts, delay, msg.get("msgid"), e,
            )

    def _process_retry_queue(self) -> None:
        while self._retry_queue:
            msg, attempts, due_at = self._retry_queue[0]
            if time.monotonic() < due_at:
                return
            self._retry_queue.popleft()
            self._dispatch_with_retry(msg, attempts)

    def _consume_forever(self) -> None:
        while True:
            if not self._native_logged_in():
                time.sleep(max(1.0, self.pull_wait_ms / 1000))
                continue
            self._process_retry_queue()
            ok = self._pull_once()
            if not ok:
                time.sleep(1)

    def run(self, main_thread: bool = True):
        if main_thread:
            self._consume_forever()
            return None
        consumer_thread = threading.Thread(target=self._consume_forever, daemon=True)
        consumer_thread.start()
        return consumer_thread.ident

    def get_base_path(self):
        return self.BASE_PATH

    def __getattr__(self, item: str):
        return self.api.exec_command(item)
