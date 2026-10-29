#!/usr/bin/env python3
"""K5 — идемпотентный seed Keycloak: realm `dev`, роли, пользователи, клиенты.

Источник правды по конфигурации — `architecture/keycloak-spec.md` §5. Скрипт можно гонять
повторно в любой момент: объекты создаются, если их нет, и обновляются, если разошлись.

Креды берутся из приватных файлов репозитория (gitignored):
  keycloak-admin.local.md  — bootstrap-admin-username/password (master-реалм)
  keycloak-users.local.md  — realm, user-test-password, admin-test-password
  keycloak-clients.local.md — секреты клиентов (скрипт дописывает новые, 0600)

Значения в вывод не попадают: печатается только сводка (realm/roles/users/clients).

Использование:
    python3 scripts/keycloak_seed.py                 # https://auth.demo-ai-lab.ru
    python3 scripts/keycloak_seed.py --base-url http://localhost:8080   # через port-forward
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
ADMIN_FILE = REPO / "keycloak-admin.local.md"
USERS_FILE = REPO / "keycloak-users.local.md"
CLIENTS_FILE = REPO / "keycloak-clients.local.md"

REALM = "dev"
REALM_DISPLAY = "demo-ai-lab (dev)"


# --- приватные файлы ----------------------------------------------------------------------

def read_kv(path: Path) -> dict[str, str]:
    """Формат `ключ: значение`, по строке на ключ; комментарии и пустые строки пропускаем."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith(("#", "<!--", "//", "`")):
            continue
        if ": " not in line:
            continue
        k, v = line.split(": ", 1)
        out[k.strip()] = v.strip()
    return out


def upsert_kv(path: Path, key: str, value: str) -> None:
    """Идемпотентно обновляет `ключ: значение` в приватном файле, сохраняя остальные строки."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}: "):
            lines[i] = f"{key}: {value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


# --- HTTP ---------------------------------------------------------------------------------

class Keycloak:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token = ""

    def call(self, method: str, path: str, body=None, *, ok=(200, 201, 204), form=False) -> Any:
        url = f"{self.base}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            if form:
                data = urllib.parse.urlencode(body).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                data = json.dumps(body).encode()
                headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                raw = resp.read()
                if resp.status not in ok:
                    raise RuntimeError(f"{method} {path} → {resp.status}")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return None
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"{method} {path} → {e.code}: {detail}") from e

    def login(self, user: str, password: str) -> None:
        tok = self.call(
            "POST",
            "/realms/master/protocol/openid-connect/token",
            {
                "client_id": "admin-cli",
                "grant_type": "password",
                "username": user,
                "password": password,
            },
            form=True,
        )
        if not tok or "access_token" not in tok:
            raise RuntimeError("не удалось получить токен админа (проверь bootstrap-креды)")
        self.token = tok["access_token"]

    # --- realm / roles / users / clients ---

    def realm_exists(self) -> bool:
        realms = self.call("GET", "/admin/realms") or []
        return any(r.get("realm") == REALM for r in realms)

    def create_realm(self) -> None:
        self.call(
            "POST",
            "/admin/realms",
            {
                "realm": REALM,
                "displayName": REALM_DISPLAY,
                "enabled": True,
                "registrationAllowed": False,
                "resetPasswordAllowed": False,
                "verifyEmail": False,
                "loginWithEmailAllowed": True,
                "editUsernameAllowed": False,
                "bruteForceProtected": True,
                "failureFactor": 5,
                "waitIncrementSeconds": 60,
                "maxFailureWaitSeconds": 900,
                "permanentLockout": False,
                "accessTokenLifespan": 300,
                "ssoSessionIdleTimeout": 1800,
                "ssoSessionMaxLifespan": 36000,
                "revokeRefreshToken": True,
                "refreshTokenMaxReuse": 0,
                "passwordPolicy": "length(16) and notUsername and notEmail",
            },
        )

    def update_realm_settings(self) -> None:
        self.call(
            "PUT",
            f"/admin/realms/{REALM}",
            {
                "bruteForceProtected": True,
                "failureFactor": 5,
                "waitIncrementSeconds": 60,
                "maxFailureWaitSeconds": 900,
                "permanentLockout": False,
                "registrationAllowed": False,
                "resetPasswordAllowed": False,
                "verifyEmail": False,
                "loginWithEmailAllowed": True,
                "editUsernameAllowed": False,
                "accessTokenLifespan": 300,
                "ssoSessionIdleTimeout": 1800,
                "ssoSessionMaxLifespan": 36000,
                "revokeRefreshToken": True,
                "refreshTokenMaxReuse": 0,
                "passwordPolicy": "length(16) and notUsername and notEmail",
            },
        )

    def role(self, name: str, description: str = "") -> dict[str, Any]:
        roles = self.call("GET", f"/admin/realms/{REALM}/roles/{name}", ok=(200, 404))
        if roles:
            return roles
        self.call("POST", f"/admin/realms/{REALM}/roles", {"name": name, "description": description})
        return self.call("GET", f"/admin/realms/{REALM}/roles/{name}")

    def make_composite(self, name: str, children: list[dict]) -> None:
        body = [{"id": c["id"], "name": c["name"]} for c in children]
        self.call("POST", f"/admin/realms/{REALM}/roles/{name}/composites", body, ok=(204, 409))

    def user(self, username: str, email: str, first: str, last: str) -> dict[str, Any]:
        found = self.call(
            "GET",
            f"/admin/realms/{REALM}/users?" + urllib.parse.urlencode({"username": username, "exact": "true"}),
        ) or []
        if found:
            return found[0]
        self.call(
            "POST",
            f"/admin/realms/{REALM}/users",
            {
                "username": username,
                "email": email,
                "firstName": first,
                "lastName": last,
                "enabled": True,
                "emailVerified": False,
            },
        )
        found = self.call(
            "GET",
            f"/admin/realms/{REALM}/users?" + urllib.parse.urlencode({"username": username, "exact": "true"}),
        ) or []
        return found[0]

    def set_password(self, user_id: str, password: str) -> None:
        self.call(
            "PUT",
            f"/admin/realms/{REALM}/users/{user_id}/reset-password",
            {"type": "password", "value": password, "temporary": False},
            ok=(204,),
        )

    def grant_realm_roles(self, user_id: str, roles: list[dict]) -> None:
        current = self.call("GET", f"/admin/realms/{REALM}/users/{user_id}/role-mappings/realm") or []
        have = {r["name"] for r in current}
        missing = [{"id": r["id"], "name": r["name"]} for r in roles if r["name"] not in have]
        if missing:
            self.call(
                "POST",
                f"/admin/realms/{REALM}/users/{user_id}/role-mappings/realm",
                missing,
                ok=(204,),
            )

    def client(self, payload: dict, secret: str | None = None) -> dict[str, Any]:
        found = self.call(
            "GET", f"/admin/realms/{REALM}/clients?" + urllib.parse.urlencode({"clientId": payload["clientId"]})
        ) or []
        if found:
            # Идемпотентный upsert: уже существующий клиент приводим к payload. Раньше здесь был
            # `return found[0]`, из-за чего правки client_payloads() (например
            # `post.logout.redirect.uris` у `gps`) на живой клиент не доезжали и выход из GPUStack
            # падал на «Invalid redirect uri».
            current = found[0]
            body = dict(payload)
            attrs = dict(current.get("attributes") or {})
            attrs.update(payload.get("attributes") or {})
            body["attributes"] = attrs
            body["secret"] = current.get("secret") or secret
            self.call("PUT", f"/admin/realms/{REALM}/clients/{current['id']}", body)
            return self.call("GET", f"/admin/realms/{REALM}/clients/{current['id']}") or current
        body = dict(payload)
        if secret:
            body["secret"] = secret
        self.call("POST", f"/admin/realms/{REALM}/clients", body, ok=(201,))
        found = self.call(
            "GET", f"/admin/realms/{REALM}/clients?" + urllib.parse.urlencode({"clientId": payload["clientId"]})
        ) or []
        return found[0]

    def client_secret(self, uuid: str) -> str:
        data = self.call("GET", f"/admin/realms/{REALM}/clients/{uuid}/client-secret") or {}
        return data.get("value", "")

    def grant_client_role(self, uuid: str, role: dict) -> None:
        svc = self.call("GET", f"/admin/realms/{REALM}/clients/{uuid}/service-account-user")
        if not svc:
            raise RuntimeError("у клиента нет service account — включи serviceAccountsEnabled")
        self.grant_realm_roles(svc["id"], [role])


# --- конфигурация §5 ----------------------------------------------------------------------

def client_payloads() -> list[dict]:
    return [
        {
            "clientId": "smoke-cli",
            "name": "K5 smoke: проверка токенов user-test/admin-test",
            "publicClient": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": False,
            "protocol": "openid-connect",
        },
        {
            "clientId": "gps",
            "name": "GPUStack (SSO служебного UI, шаг 1)",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "protocol": "openid-connect",
            "redirectUris": ["https://api.demo-ai-lab.ru/auth/oidc/callback"],
            "webOrigins": ["https://api.demo-ai-lab.ru"],
            "attributes": {
                # GPUStack считает post_logout_redirect_uri от server_external_url — это ровно
                # `https://api.demo-ai-lab.ru` без пути, поэтому нужен и bare-origin вариант:
                # `/*` в Keycloak матчит только пути с завершающим слэшем.
                "post.logout.redirect.uris": "https://api.demo-ai-lab.ru/*##https://api.demo-ai-lab.ru"
            },
        },
        {
            "clientId": "agent-runtime",
            "name": "M2M: агентские рантаймы (шаг 3)",
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "protocol": "openid-connect",
        },
        {
            "clientId": "mcp",
            "name": "MCP Registry: админ/публикация (шаг 3)",
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "protocol": "openid-connect",
        },
        {
            "clientId": "owu",
            "name": "Open WebUI (шаг 2, SSO)",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "protocol": "openid-connect",
            "redirectUris": ["https://owu.demo-ai-lab.ru/oauth/oidc/callback"],
            "webOrigins": ["https://owu.demo-ai-lab.ru"],
        },
        {
            "clientId": "spk",
            "name": "Speakr (шаг 2, SSO)",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "protocol": "openid-connect",
            "redirectUris": ["https://spk.demo-ai-lab.ru/auth/sso/callback"],
            "webOrigins": ["https://spk.demo-ai-lab.ru"],
        },
        {
            "clientId": "lng",
            "name": "Langfuse (шаг 2, SSO)",
            "publicClient": False,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "protocol": "openid-connect",
            # next-auth (Langfuse) регистрирует провайдер как `keycloak` → callback ровно
            # `/api/auth/callback/keycloak` (сверено по исходникам langfuse v4.71.0,
            # web/src/server/auth.ts); путь угадывать нельзя — проверять GET /api/auth/providers.
            "redirectUris": ["https://lng.demo-ai-lab.ru/api/auth/callback/keycloak"],
            "webOrigins": ["https://lng.demo-ai-lab.ru"],
            "attributes": {
                # next-auth по умолчанию шлёт PKCE (checks=["pkce","state"]) — клиент обязан
                # объявить метод, иначе Keycloak режет code_challenge.
                "pkce.code.challenge.method": "S256"
            },
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="https://auth.demo-ai-lab.ru")
    ap.add_argument("--skip-users", action="store_true", help="только realm/роли/клиенты")
    args = ap.parse_args()

    admin = read_kv(ADMIN_FILE)
    users = read_kv(USERS_FILE)
    kc = Keycloak(args.base_url)
    kc.login(admin["bootstrap-admin-username"], admin["bootstrap-admin-password"])

    if not kc.realm_exists():
        kc.create_realm()
    else:
        kc.update_realm_settings()

    role_user = kc.role("app-user", "обычный пользователь приложений стенда")
    role_admin = kc.role("app-admin", "администратор приложений (не админ Keycloak)")
    role_agent = kc.role("agent-service", "машинная идентичность агентских рантаймов")
    kc.make_composite("app-admin", [role_user])

    created_users = 0
    if not args.skip_users:
        u1 = kc.user("user-test", "user-test@demo-ai-lab.ru", "Test", "User")
        kc.set_password(u1["id"], users["user-test-password"])
        kc.grant_realm_roles(u1["id"], [role_user])
        u2 = kc.user("admin-test", "admin-test@demo-ai-lab.ru", "Admin", "Test")
        kc.set_password(u2["id"], users["admin-test-password"])
        kc.grant_realm_roles(u2["id"], [role_admin])
        created_users = 2

    clients = read_kv(CLIENTS_FILE)
    new_secrets = 0
    for payload in client_payloads():
        is_confidential = not payload["publicClient"]
        secret = None
        if is_confidential:
            secret = clients.get(f"{payload['clientId']}-client-secret") or secrets.token_urlsafe(32)
        obj = kc.client(payload, secret)
        if is_confidential:
            actual = kc.client_secret(obj["id"])
            if clients.get(f"{payload['clientId']}-client-secret") != actual:
                upsert_kv(CLIENTS_FILE, f"{payload['clientId']}-client-secret", actual)
                new_secrets += 1
        if payload["clientId"] == "agent-runtime":
            kc.grant_client_role(obj["id"], role_agent)

    print(f"realm: {REALM} ok")
    print(f"roles: 3 (app-user, app-admin⊃app-user, agent-service)")
    print(f"users: {created_users}")
    print(f"clients: {len(client_payloads())} (секретов записано в keycloak-clients.local.md: {new_secrets})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
