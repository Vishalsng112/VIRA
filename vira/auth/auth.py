import bcrypt
import secrets
import string
from typing import Optional

from .database import get_user_by_username, create_user, update_password, count_users

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

def generate_recovery_code(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def hash_recovery_code(code: str) -> str:
    return hash_password(code)  # reuse bcrypt hashing

def verify_recovery_code(code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(code.encode('utf-8'), code_hash.encode('utf-8'))

def admin_exists() -> bool:
    return count_users() > 0

def create_admin(username: str, password: str) -> str:
    """Create admin user and return recovery code."""
    if admin_exists():
        raise RuntimeError("Admin already exists")
    recovery_code = generate_recovery_code()
    pwd_hash = hash_password(password)
    rec_hash = hash_recovery_code(recovery_code)
    create_user(username, pwd_hash, rec_hash)
    return recovery_code

def authenticate_user(username: str, password: str) -> bool:
    user = get_user_by_username(username)
    if not user:
        return False
    return verify_password(password, user["password_hash"])

def reset_password(username: str, recovery_code: str, new_password: str) -> bool:
    user = get_user_by_username(username)
    if not user:
        return False
    if not verify_recovery_code(recovery_code, user["recovery_code_hash"]):
        return False
    new_hash = hash_password(new_password)
    update_password(username, new_hash)
    return True


def get_admin_username() -> Optional[str]:
    from .database import get_connection
    with get_connection() as conn:
        row = conn.execute("SELECT username FROM users ORDER BY id LIMIT 1").fetchone()
        return row["username"] if row else None

def update_recovery_code(username: str, new_hash: str) -> None:
    from .database import get_connection
    with get_connection() as conn:
        conn.execute("UPDATE users SET recovery_code_hash = ? WHERE username = ?", (new_hash, username))
        conn.commit()
        