"""Password hashing and tokens. No secret is stored in the clear: passwords are scrypt hashes,
session and link tokens are stored as SHA-256 of a 256-bit random value."""
import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1  # scrypt cost: about 50 ms, 16 MB


def hash_password(password):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=N, r=R, p=P)
    return f"scrypt${N}${R}${P}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def check_password(password, stored):
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def new_token():
    return secrets.token_urlsafe(32)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def weak_password(password):
    """Reason a password is refused, or None. Length matters more than character classes."""
    if len(password) < 10:
        return "τουλάχιστον 10 χαρακτήρες"
    if len(set(password)) < 5:
        return "πολύ επαναλαμβανόμενος"
    return None
