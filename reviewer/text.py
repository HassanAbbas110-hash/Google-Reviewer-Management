"""Small shared text helpers."""
import hashlib


def digest(text):
    """Stable hash of exact reply text, used to bind approvals to the words approved."""
    return hashlib.sha256(str(text or '').encode('utf-8')).hexdigest()
