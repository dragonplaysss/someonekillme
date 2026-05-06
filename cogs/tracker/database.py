import sqlite3

class TrackerDB:
    def __init__(self):
        self.db = sqlite3.connect("tracker.db")
        self.cur = self.db.cursor()

        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS tracked (
            user_id INTEGER PRIMARY KEY,
            last_status INTEGER DEFAULT 0
        )
        """)
        self.db.commit()

    def add(self, uid):
        self.cur.execute("INSERT OR IGNORE INTO tracked VALUES (?, 0)", (uid,))
        self.db.commit()

    def remove(self, uid):
        self.cur.execute("DELETE FROM tracked WHERE user_id=?", (uid,))
        self.db.commit()

    def all(self):
        self.cur.execute("SELECT user_id, last_status FROM tracked")
        return self.cur.fetchall()

    def update(self, uid, status):
        self.cur.execute("UPDATE tracked SET last_status=? WHERE user_id=?", (status, uid))
        self.db.commit()