# [memory_crud.py/Soveranima]
#     Copyright (C) 2026  Toolspeter
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
永久記憶 CRUD 操作模組
提供永久記憶的增刪改查功能
"""

import json
from datetime import datetime, timezone


def add_permanent_memory(db, user_id: str, title: str, content: str, importance: int = 5):
    """新增永久記憶"""
    cur = db.cursor()
    now_utc = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """INSERT INTO permanent_memory (user_id, title, content, importance, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, title, content, importance, now_utc, now_utc)
    )
    db.commit()
    return cur.lastrowid


def get_permanent_memories(db, user_id: str, limit: int = None):
    """取得永久記憶列表"""
    cur = db.cursor()
    if limit:
        cur.execute(
            """SELECT id, title, content, importance, created_at, updated_at
               FROM permanent_memory
               WHERE user_id = ?
               ORDER BY importance DESC, created_at DESC
               LIMIT ?""",
            (user_id, limit)
        )
    else:
        cur.execute(
            """SELECT id, title, content, importance, created_at, updated_at
               FROM permanent_memory
               WHERE user_id = ?
               ORDER BY importance DESC, created_at DESC""",
            (user_id,)
        )
    return cur.fetchall()


def update_permanent_memory(db, memory_id: int, title: str = None, content: str = None, importance: int = None):
    """更新永久記憶"""
    cur = db.cursor()
    now_utc = datetime.now(timezone.utc).isoformat()

    updates = []
    params = []

    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if content is not None:
        updates.append("content = ?")
        params.append(content)
    if importance is not None:
        updates.append("importance = ?")
        params.append(importance)

    if not updates:
        return False

    updates.append("updated_at = ?")
    params.append(now_utc)
    params.append(memory_id)

    query = f"UPDATE permanent_memory SET {', '.join(updates)} WHERE id = ?"
    cur.execute(query, params)
    db.commit()
    return cur.rowcount > 0


def delete_permanent_memory(db, memory_id: int):
    """刪除永久記憶"""
    cur = db.cursor()
    cur.execute("DELETE FROM permanent_memory WHERE id = ?", (memory_id,))
    db.commit()
    return cur.rowcount > 0


def get_permanent_memory_stats(db, user_id: str):
    """取得永久記憶統計資訊"""
    cur = db.cursor()
    cur.execute(
        "SELECT COUNT(*) as count FROM permanent_memory WHERE user_id = ?",
        (user_id,)
    )
    row = cur.fetchone()
    return row[0] if row else 0
