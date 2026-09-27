from __future__ import annotations

import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from awas.auth.passwords import hash_password, verify_password
from awas.auth.tokens import new_token, token_hash
from awas.config import SecuritySettings
from awas.models import AuditLog, LoginAttempt, User, WebSession
from awas.models.auth import utc_now

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{2,31}$")
DELETED_USER_DISPLAY_NAME = "Gelöschter Benutzer"


class UserInputError(ValueError):
    pass


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise UserInputError(
            "Der Benutzername muss 3 bis 32 Zeichen lang sein, mit einem Buchstaben beginnen "
            "und darf nur Kleinbuchstaben, Zahlen, Punkt, _ und - enthalten."
        )
    return normalized


def validate_display_name(display_name: str) -> str:
    normalized = " ".join(display_name.strip().split())
    if not 1 <= len(normalized) <= 128:
        raise UserInputError("Der Anzeigename muss 1 bis 128 Zeichen lang sein.")
    return normalized


def validate_new_password(password: str, password_confirmation: str) -> None:
    if password != password_confirmation:
        raise UserInputError("Die beiden Passwörter stimmen nicht überein.")
    if not password:
        raise UserInputError("Das Passwort darf nicht leer sein.")


def add_audit_entry(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    target: User | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    ip_address: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            action=action,
            target_type="user" if target else target_type,
            target_id=target.id if target else target_id,
            ip_address=ip_address,
            details=details,
        )
    )


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
    role: str,
    actor: User | None = None,
    ip_address: str | None = None,
    must_change_password: bool = True,
) -> User:
    normalized_username = validate_username(username)
    normalized_display_name = validate_display_name(display_name)
    if role not in {"admin", "user"}:
        raise UserInputError("Unbekannte Benutzerrolle.")
    validate_new_password(password, password_confirmation)
    if db.scalar(select(User.id).where(User.username == normalized_username)) is not None:
        raise UserInputError("Dieser Benutzername ist bereits vergeben.")

    user = User(
        username=normalized_username,
        display_name=normalized_display_name,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=must_change_password,
        created_by_id=actor.id if actor else None,
    )
    db.add(user)
    db.flush()
    add_audit_entry(
        db,
        "user.created",
        actor=actor,
        target=user,
        ip_address=ip_address,
        details={"role": role},
    )
    db.commit()
    return user


def login_is_limited(
    db: Session, username: str, ip_address: str, security: SecuritySettings
) -> bool:
    cutoff = utc_now() - timedelta(minutes=security.login_window_minutes)
    failures_for_account = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.username == username,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    failures_for_ip = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
    )
    return bool(
        (failures_for_account or 0) >= security.login_max_attempts_per_account
        or (failures_for_ip or 0) >= security.login_max_attempts_per_ip
    )


def authenticate_user(
    db: Session,
    *,
    username: str,
    password: str,
    ip_address: str,
    security: SecuritySettings,
) -> tuple[User | None, bool]:
    normalized_username = normalize_username(username)[:32]
    db.execute(
        delete(LoginAttempt).where(LoginAttempt.attempted_at < utc_now() - timedelta(days=30))
    )

    if login_is_limited(db, normalized_username, ip_address, security):
        add_audit_entry(
            db,
            "login.blocked",
            ip_address=ip_address,
            details={"username": normalized_username},
        )
        db.commit()
        return None, True

    user = db.scalar(select(User).where(User.username == normalized_username))
    password_valid = verify_password(password, user.password_hash if user else None)
    if user is None or not password_valid or not user.is_active:
        db.add(
            LoginAttempt(
                username=normalized_username,
                ip_address=ip_address,
                succeeded=False,
            )
        )
        add_audit_entry(
            db,
            "login.failed",
            ip_address=ip_address,
            details={"username": normalized_username},
        )
        db.commit()
        return None, False

    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.username == normalized_username,
            LoginAttempt.ip_address == ip_address,
        )
    )
    db.add(
        LoginAttempt(
            username=normalized_username,
            ip_address=ip_address,
            succeeded=True,
        )
    )
    user.last_login_at = utc_now()
    add_audit_entry(db, "login.succeeded", actor=user, target=user, ip_address=ip_address)
    db.commit()
    return user, False


def create_web_session(
    db: Session,
    user: User,
    *,
    security: SecuritySettings,
    ip_address: str,
    user_agent: str | None,
) -> str:
    raw_token = new_token()
    now = utc_now()
    db.add(
        WebSession(
            token_hash=token_hash(raw_token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=security.session_lifetime_hours),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:512] or None,
        )
    )
    db.commit()
    return raw_token


def resolve_web_session(db: Session, raw_token: str) -> WebSession | None:
    web_session = db.scalar(
        select(WebSession)
        .options(joinedload(WebSession.user))
        .where(WebSession.token_hash == token_hash(raw_token))
    )
    if web_session is None:
        return None
    if web_session.expires_at <= utc_now() or not web_session.user.is_active:
        db.delete(web_session)
        db.commit()
        return None
    if web_session.last_seen_at < utc_now() - timedelta(minutes=5):
        web_session.last_seen_at = utc_now()
        db.commit()
    return web_session


def destroy_session(db: Session, raw_token: str | None) -> None:
    if raw_token:
        db.execute(delete(WebSession).where(WebSession.token_hash == token_hash(raw_token)))
        db.commit()


def destroy_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(WebSession).where(WebSession.user_id == user_id))


def anonymize_deleted_user(
    db: Session,
    target: User,
    *,
    actor: User,
    ip_address: str | None = None,
) -> None:
    """Remove an account while retaining an anonymous attribution tombstone."""
    original_username = target.username
    now = utc_now()
    destroy_user_sessions(db, target.id)
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == original_username))

    for entry in db.scalars(
        select(AuditLog).where(AuditLog.action.in_(("login.failed", "login.blocked")))
    ):
        if entry.details and entry.details.get("username") == original_username:
            entry.details = {**entry.details, "username": "gelöschter-benutzer"}

    add_audit_entry(
        db,
        "user.deleted",
        actor=actor,
        target=target,
        ip_address=ip_address,
    )
    target.username = _new_deleted_username(db)
    target.display_name = DELETED_USER_DISPLAY_NAME
    target.password_hash = hash_password(secrets.token_urlsafe(48))
    target.role = "user"
    target.is_active = False
    target.must_change_password = False
    target.last_login_at = None
    target.password_changed_at = now
    target.updated_at = now
    target.deleted_at = now
    db.commit()


def _new_deleted_username(db: Session) -> str:
    while True:
        candidate = f"deleted-{secrets.token_hex(12)}"
        if db.scalar(select(User.id).where(User.username == candidate)) is None:
            return candidate


def active_admin_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        or 0
    )
