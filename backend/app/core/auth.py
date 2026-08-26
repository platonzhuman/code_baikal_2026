from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import get_settings


def check_login(login: str, password: str) -> str | None:
    """Сверка логина/пароля с кредами из настроек. Возвращает роль или None."""
    for role, (r_login, r_pass) in get_settings().role_credentials.items():
        # сравниваем через bytes — compare_digest не поддерживает не-ASCII str
        if hmac.compare_digest(login.encode(), r_login.encode()) and \
           hmac.compare_digest(password.encode(), r_pass.encode()):
            return role
    return None


def make_token(role: str) -> str:
    """Подписанный токен: base64( json{role,exp} + '.' + hmac )."""
    s = get_settings()
    exp = int(time.time()) + s.token_ttl
    payload = base64.urlsafe_b64encode(json.dumps({"role": role, "exp": exp}).encode()).decode()
    sig = hmac.new(s.app_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str) -> str | None:
    """Проверка токена -> роль (или None, если невалиден/истёк)."""
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    s = get_settings()
    expected = hmac.new(s.app_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except Exception:
        return None
    if data.get("exp", 0) < int(time.time()):
        return None
    return data.get("role")
