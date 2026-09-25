"""Separate V2 account metadata. No passwords, upstream cookies, or OAuth tokens."""
import os
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / "onboarding.db"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS accounts (email TEXT, school TEXT, PRIMARY KEY(email, school))")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (email TEXT PRIMARY KEY, attempted REAL)")
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path)

    def exists(self, email, school):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM accounts WHERE email=? AND school=?", (email.casefold(), school)).fetchone() is not None

    def account(self, email, school):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO accounts(email,school) VALUES(?,?)", (email.casefold(), school))

    def reserve_attempt(self, email):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempted FROM attempts WHERE email=?", (email.casefold(),)).fetchone()
            if row and time.time() - row[0] < 300:
                return False
            db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?)", (email.casefold(), time.time()))
            return True
