import base64
import hashlib
import hmac
import re
import secrets

from fastapi import HTTPException, Request

from db import db
from models import AuthSession, Project, ProjectMembership, ROLE_MEMBER, ROLE_OWNER, User


PASSWORD_ITERATIONS = 150_000
USERNAME_RE = re.compile(r"^[\w.-]{3,40}$", re.UNICODE)


def api_error(message, status_code):
    raise HTTPException(status_code=status_code, detail=message)


def normalize_username(value):
    return str(value or "").strip().lower()


def _hash_password(password, salt=None, iterations=PASSWORD_ITERATIONS):
    salt = salt or secrets.token_urlsafe(18)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    encoded = base64.b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def _verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt, _ = str(stored_hash or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = _hash_password(password, salt=salt, iterations=int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(expected, stored_hash)


def _token_hash(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _bearer_token(request: Request):
    auth_header = request.headers.get("authorization") or ""
    prefix = "bearer "
    if not auth_header.lower().startswith(prefix):
        return None
    token = auth_header[len(prefix):].strip()
    return token or None


def _issue_session(user):
    token = secrets.token_urlsafe(36)
    db.session.add(AuthSession(user_id=user.id, token_hash=_token_hash(token)))
    return token


def _claim_unassigned_projects(user):
    for project in Project.query.order_by(Project.created_at.asc()).all():
        if project.memberships.count() > 0:
            continue
        project.created_by_id = user.id
        db.session.add(ProjectMembership(
            project_id=project.id,
            user_id=user.id,
            role=ROLE_OWNER,
        ))


def register_user(payload):
    username = normalize_username(payload.get("username"))
    password = str(payload.get("password") or "")
    display_name = str(payload.get("display_name") or "").strip() or username

    if not USERNAME_RE.match(username):
        api_error("Логин должен быть 3-40 символов: буквы, цифры, точка, дефис или _", 400)
    if len(password) < 6:
        api_error("Пароль должен быть не короче 6 символов", 400)
    if User.query.filter_by(username=username).first():
        api_error("Пользователь с таким логином уже существует", 409)

    is_first_user = User.query.count() == 0
    user = User(
        username=username,
        display_name=display_name,
        password_hash=_hash_password(password),
    )
    db.session.add(user)
    db.session.flush()

    if is_first_user:
        _claim_unassigned_projects(user)

    token = _issue_session(user)
    db.session.commit()
    return {"token": token, "user": user.to_dict()}


def login_user(payload):
    username = normalize_username(payload.get("username"))
    password = str(payload.get("password") or "")
    user = User.query.filter_by(username=username).first()
    if not user or not _verify_password(password, user.password_hash):
        api_error("Неверный логин или пароль", 401)

    token = _issue_session(user)
    db.session.commit()
    return {"token": token, "user": user.to_dict()}


def current_user(request: Request):
    token = _bearer_token(request)
    if not token:
        return None
    session = AuthSession.query.filter_by(token_hash=_token_hash(token)).first()
    return session.user if session and session.user else None


def require_user(request: Request):
    user = current_user(request)
    if not user:
        api_error("Требуется вход в аккаунт", 401)
    return user


def logout_user(request: Request):
    token = _bearer_token(request)
    if token:
        session = AuthSession.query.filter_by(token_hash=_token_hash(token)).first()
        if session:
            db.session.delete(session)
            db.session.commit()
    return {"ok": True}


def membership_for(user, project_id):
    return ProjectMembership.query.filter_by(user_id=user.id, project_id=project_id).first()


def require_project_access(user, project_id):
    project = db.session.get(Project, project_id)
    if not project:
        api_error("Проект не найден", 404)

    membership = membership_for(user, project_id)
    if not membership:
        api_error("Нет доступа к этому проекту", 403)
    return project, membership


def require_project_owner(user, project_id):
    project, membership = require_project_access(user, project_id)
    if membership.role != ROLE_OWNER:
        api_error("Это действие доступно только owner проекта", 403)
    return project, membership


def add_project_member(project, username):
    target_username = normalize_username(username)
    if not target_username:
        api_error("Укажите логин пользователя", 400)

    target = User.query.filter_by(username=target_username).first()
    if not target:
        api_error("Пользователь с таким логином не найден", 404)

    membership = ProjectMembership.query.filter_by(
        project_id=project.id,
        user_id=target.id,
    ).first()
    if membership:
        return membership

    membership = ProjectMembership(
        project_id=project.id,
        user_id=target.id,
        role=ROLE_MEMBER,
    )
    db.session.add(membership)
    db.session.commit()
    return membership


def remove_project_member(project, user_id):
    membership = ProjectMembership.query.filter_by(
        project_id=project.id,
        user_id=user_id,
    ).first()
    if not membership:
        api_error("Участник не найден", 404)
    if membership.role == ROLE_OWNER:
        api_error("Владельца проекта нельзя удалить из участников", 403)

    db.session.delete(membership)
    db.session.commit()
    return {"deleted": user_id}
