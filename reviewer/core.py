"""Durable ingestion only. Eligibility is not permission to send a network request.

The future publisher must recheck consent, source versions and current Google
replies immediately before writing. This module never publishes anything.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def decision(*, consent: bool, facts_approved: bool, auto_enabled: bool,
             risk: str, valid: bool, existing_reply: str = '') -> str:
    if existing_reply.strip():
        return 'already_replied'
    if consent is not True or facts_approved is not True or auto_enabled is not True:
        return 'needs_approval'
    if valid is not True or risk != 'routine':
        return 'needs_approval'
    return 'eligible'


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS reviews (
                business_id TEXT NOT NULL, review_id TEXT NOT NULL,
                text TEXT NOT NULL, rating INTEGER NOT NULL,
                existing_reply TEXT NOT NULL, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL,
                PRIMARY KEY (business_id, review_id))''')

    def ingest(self, business_id: str, review_id: str, text: str,
               rating: int, existing_reply: str = '') -> str:
        if not business_id.strip() or not review_id.strip():
            raise ValueError('Business and review identifiers are required')
        if type(rating) is not int or not 1 <= rating <= 5:
            raise ValueError('Rating must be an integer from 1 to 5')
        fingerprint = hashlib.sha256(json.dumps(
            [text, rating, existing_reply], ensure_ascii=False).encode()).hexdigest()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute(
                'SELECT fingerprint FROM reviews WHERE business_id=? AND review_id=?',
                (business_id, review_id)).fetchone()
            if old and old[0] == fingerprint:
                return 'unchanged'
            state = ('already_replied' if existing_reply.strip() else
                     'needs_approval' if old else 'pending')
            db.execute('''INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_id, review_id) DO UPDATE SET
                text=excluded.text, rating=excluded.rating,
                existing_reply=excluded.existing_reply,
                fingerprint=excluded.fingerprint, state=excluded.state''',
                       (business_id, review_id, text, rating, existing_reply,
                        fingerprint, state))
            return state

    def get(self, business_id: str, review_id: str) -> dict | None:
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                'SELECT * FROM reviews WHERE business_id=? AND review_id=?',
                (business_id, review_id)).fetchone()
            return dict(row) if row else None
