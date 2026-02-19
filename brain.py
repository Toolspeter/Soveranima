import json
import os
import sqlite3
import subprocess
from datetime import datetime
from openai import OpenAI
from prompts import SYSTEM_PROMPT, HEARTBEAT_PROMPT

try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

# AI 可以升級的檔案列表
EVOLVABLE_FILES = ["brain.py", "main.py"]


class Soul:
    def __init__(self, api_key: str, base_url: str = None, owner_id: str = None, model: str = "gemini-2.0-flash", tavily_api_key: str = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.owner_id = owner_id
        self.model = model
        self.db = sqlite3.connect("memory.db", check_same_thread=False)
        self._init_db()

        # Tavily 搜尋客戶端
        self.tavily = None
        if TAVILY_AVAILABLE and tavily_api_key:
            self.tavily = TavilyClient(api_key=tavily_api_key)

    def _init_db(self):
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY,
                user_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY,
                user_id TEXT UNIQUE,
                content TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY,
                user_id TEXT UNIQUE,
                data TEXT DEFAULT '{}',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS last_interaction (
                user_id TEXT PRIMARY KEY,
                timestamp DATETIME,
                channel_id TEXT
            )
        """)
        try:
            cur.execute("ALTER TABLE last_interaction ADD COLUMN channel_id TEXT")
        except Exception:
            pass
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                temperature REAL DEFAULT 0.8,
                heartbeat_enabled INTEGER DEFAULT 1,
                heartbeat_interval INTEGER DEFAULT 30,
                timezone_offset INTEGER DEFAULT 0
            )
        """)
        # 資料庫遷移：為舊表新增 timezone_offset 欄位
        try:
            cur.execute("ALTER TABLE user_settings ADD COLUMN timezone_offset INTEGER DEFAULT 0")
        except Exception:
            pass  # 欄位已存在則忽略
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pending_evolutions (
                id INTEGER PRIMARY KEY,
                reason TEXT,
                file_path TEXT,
                old_code TEXT,
                new_code TEXT,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                reviewed_at DATETIME,
                reviewed_by TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 預設需要手動批准
        cur.execute("""
            INSERT OR IGNORE INTO global_settings (key, value) VALUES ('approval_required', '1')
        """)
        self.db.commit()

    def is_owner(self, user_id: str) -> bool:
        """檢查是否為機器人擁有者"""
        return self.owner_id and str(user_id) == str(self.owner_id)

    def get_global_setting(self, key: str, default: str = None) -> str | None:
        """取得全域設定"""
        cur = self.db.cursor()
        cur.execute("SELECT value FROM global_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_global_setting(self, key: str, value: str) -> bool:
        """設定全域設定"""
        cur = self.db.cursor()
        cur.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """, (key, value))
        self.db.commit()
        return True

    def is_evolution_enabled(self) -> bool:
        """檢查自我演化是否啟用（永遠為 True，保留此方法以維持相容性）"""
        return True

    def is_approval_required(self) -> bool:
        """檢查升級是否需要手動批准"""
        return self.get_global_setting("approval_required", "1") == "1"

    def search_web(self, query: str, max_results: int = 3) -> str:
        """使用 Tavily 搜尋網路，回傳搜尋結果摘要"""
        if not self.tavily:
            return ""

        def _try_auto_calibrate(content):
            try:
                import re
                from datetime import timezone
                now_utc = datetime.now(timezone.utc)
                # 增加日期驗證：檢查內容中是否包含當前年份，防止誤信過期資訊
                if str(now_utc.year) not in content:
                    return False

                match = re.search(r'(\d{1,2}):(\d{2}):(\d{2})', content)
                if match:
                    remote_hour = int(match.group(1))
                    local_utc_hour = now_utc.hour
                    bias = remote_hour - local_utc_hour
                    if bias > 12: bias -= 24
                    if bias < -12: bias += 24
                    
                    # 檢查冷卻時間 (7天)
                    from datetime import timedelta
                    last_sync_str = self.get_global_setting("last_time_sync_utc")
                    if last_sync_str:
                        last_sync = datetime.fromisoformat(last_sync_str)
                        # 確保比對時兩者皆為 offset-aware (UTC)
                        last_sync_aware = last_sync.replace(tzinfo=timezone.utc) if last_sync.tzinfo is None else last_sync
                        if now_utc - last_sync_aware < timedelta(days=7):
                            return False
                    
                    self.set_global_setting("system_time_bias", str(bias))
                    self.set_global_setting("last_time_sync_utc", now_utc.isoformat())
                    print(f"[Auto-Calibration] Clock offset adjusted to {bias}h via Tavily.")
                    return True
            except: pass
            return False

        try:
            response = self.tavily.search(
                query=query,
                search_depth="basic",
                max_results=max_results,
                include_answer=True
            )

            results = []
            if response.get("answer"):
                results.append(f"摘要：{response['answer']}")

            for r in response.get("results", [])[:max_results]:
                source_url = r.get('url', '未知來源')
                results.append(f"• {r.get('title', '')}: {r.get('content', '')[:200]}...\n  (來源: {source_url})")

            return "\n".join(results) if results else ""
        except Exception as e:
            print(f"搜尋錯誤: {e}")
            return ""

    def _get_source_code(self) -> str:
        """取得可升級檔案的程式碼"""
        source_parts = []
        base_dir = os.path.dirname(os.path.abspath(__file__))

        for filename in EVOLVABLE_FILES:
            filepath = os.path.join(base_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                source_parts.append(f"=== {filename} ===\n{content}")
            except Exception:
                pass

        return "\n\n".join(source_parts)

    def get_user_now(self, user_id: str):
        """取得使用者在地時間 (基於 UTC 偏移與系統校準)"""
        from datetime import timezone, timedelta
        settings = self.get_user_settings(user_id)
        user_offset = settings.get("timezone_offset", 0)
        # 取得系統校準值（補償伺服器時鐘誤差）
        system_bias = int(self.get_global_setting("system_time_bias", "0"))
        return datetime.now(timezone.utc) + timedelta(hours=user_offset + system_bias)

    def get_user_settings(self, user_id: str) -> dict:
        """取得使用者設定"""
        cur = self.db.cursor()
        cur.execute("SELECT temperature, heartbeat_enabled, heartbeat_interval, timezone_offset FROM user_settings WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return {
                "temperature": row[0],
                "heartbeat_enabled": bool(row[1]),
                "heartbeat_interval": row[2],
                "timezone_offset": row[3]
            }
        # 預設值：Owner 為 +8, 其它為 0
        default_offset = 8 if self.is_owner(user_id) else 0
        return {
            "temperature": 0.8,
            "heartbeat_enabled": True,
            "heartbeat_interval": 30,
            "timezone_offset": default_offset
        }

    def update_user_setting(self, user_id: str, key: str, value) -> bool:
        """更新使用者設定"""
        valid_keys = ["temperature", "heartbeat_enabled", "heartbeat_interval", "timezone_offset"]
        if key not in valid_keys:
            return False

        cur = self.db.cursor()
        cur.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)", (user_id,))
        cur.execute(f"UPDATE user_settings SET {key} = ? WHERE user_id = ?", (value, user_id))
        self.db.commit()
        return True

    def get_context(self, user_id: str) -> dict:
        cur = self.db.cursor()

        cur.execute("""
            SELECT role, content FROM messages
            WHERE user_id = ? ORDER BY timestamp DESC LIMIT 15
        """, (user_id,))
        messages = [{"role": r, "content": c} for r, c in reversed(cur.fetchall())]

        cur.execute("SELECT content FROM journal WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        journal = row[0] if row else ""

        cur.execute("SELECT data FROM facts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        facts = json.loads(row[0]) if row else {}

        return {"messages": messages, "journal": journal, "facts": facts}

    def get_status(self, user_id: str) -> dict:
        """取得使用者的記憶統計"""
        cur = self.db.cursor()

        # 訊息數量
        cur.execute("SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,))
        message_count = cur.fetchone()[0]

        # 日誌長度
        cur.execute("SELECT content FROM journal WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        journal_length = len(row[0]) if row else 0

        # 事實數量
        cur.execute("SELECT data FROM facts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        facts_count = len(json.loads(row[0])) if row else 0

        # 最後互動時間
        cur.execute("SELECT timestamp FROM last_interaction WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            from datetime import timezone, timedelta
            try:
                last_utc = datetime.fromisoformat(row[0])
                if last_utc.tzinfo is None:
                    last_utc = last_utc.replace(tzinfo=timezone.utc)
                settings = self.get_user_settings(user_id)
                offset = settings.get("timezone_offset", 0)
                system_bias = int(self.get_global_setting("system_time_bias", "0"))
                user_last = last_utc + timedelta(hours=offset + system_bias)
                last_interaction = user_last.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                last_interaction = row[0]
        else:
            last_interaction = "從未"

        # 使用者設定
        settings = self.get_user_settings(user_id)

        return {
            "message_count": message_count,
            "journal_length": journal_length,
            "facts_count": facts_count,
            "last_interaction": last_interaction,
            "settings": settings
        }

    def forget(self, user_id: str, forget_type: str = "messages") -> dict:
        """清除使用者記憶"""
        cur = self.db.cursor()

        if forget_type == "messages":
            cur.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            self.db.commit()
            return {"success": True, "message": "對話記錄已清除"}
        elif forget_type == "journal":
            cur.execute("DELETE FROM journal WHERE user_id = ?", (user_id,))
            self.db.commit()
            return {"success": True, "message": "生活日誌已清除"}
        elif forget_type == "facts":
            cur.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
            self.db.commit()
            return {"success": True, "message": "事實清單已清除"}
        elif forget_type == "all":
            cur.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            cur.execute("DELETE FROM journal WHERE user_id = ?", (user_id,))
            cur.execute("DELETE FROM facts WHERE user_id = ?", (user_id,))
            cur.execute("DELETE FROM last_interaction WHERE user_id = ?", (user_id,))
            self.db.commit()
            return {"success": True, "message": "所有記憶已清除"}
        else:
            return {"success": False, "message": "無效的清除類型"}

    def think(self, user_id: str, user_input: str, image_url: str = None) -> dict:
        # 先取得歷史紀錄，再儲存當前訊息，避免在 Prompt 中重複出現最新訊息導致 AI 誤判
        ctx = self.get_context(user_id)
        self._save_message(user_id, "user", user_input)
        settings = self.get_user_settings(user_id)

        # AI 永遠可以反思程式碼
        source_code = self._get_source_code()
        existing_evolutions = self.get_pending_evolutions()
        evo_list = ""
        if existing_evolutions:
            next_id = max([e['id'] for e in existing_evolutions]) + 1 if existing_evolutions else 1
            evo_list = f"\n[升級請求狀態 - 下一個編號預計為 #{next_id}]\n"
            for e in existing_evolutions[:10]:
                status_emoji = "⏳" if e['status'] == 'pending' else ("✅" if e['status'] == 'approved' else "❌")
                evo_list += f"{status_emoji} #{e['id']} ({e['file_path']}): {e['reason'][:50]}...\n"

        user_now = self.get_user_now(user_id)
        context_prompt = f"""
[當前時間]
{user_now.strftime("%Y年%m月%d日 %H:%M:%S")} (星期{['一','二','三','四','五','六','日'][user_now.weekday()]})

[生活日誌]
{ctx['journal'] or '（尚無紀錄）'}

[事實清單]
{json.dumps(ctx['facts'], ensure_ascii=False, indent=2)}

[可升級的程式碼]
{source_code}
{evo_list}
[最近對話]
"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT + context_prompt}]
        messages.extend(ctx['messages'])

        # 處理多模態內容
        user_content = [{"type": "text", "text": user_input}]
        if image_url:
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})
        messages.append({"role": "user", "content": user_content})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings["temperature"]
        )

        raw = response.choices[0].message.content
        result = self._parse_response(raw)

        # 處理搜尋請求
        if result.get('search_query') and self.tavily:
            search_results = self.search_web(result['search_query'])
            if search_results:
                self._save_message(user_id, "system", f"[搜尋結果: {result['search_query']}]\n{search_results}")
                
                # 準備二次思考，將原始 JSON 回覆傳回給模型以保持上下文連貫
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": f"[系統通知] 搜尋已完成：\n{search_results}\n請根據搜尋結果給予主人最終回覆。"})
                
                second_response = self.client.chat.completions.create(
                    model=self.model, 
                    messages=messages, 
                    temperature=settings["temperature"]
                )
                
                raw_second = second_response.choices[0].message.content
                second_result = self._parse_response(raw_second)
                
                # 合併元數據，確保第一次思考產生的日誌、事實或演化標記不會遺失
                for key, value in result.items():
                    if key not in ['content', 'inner_thought', 'decision', 'search_query'] and key not in second_result:
                        second_result[key] = value
                result = second_result

        # 統一儲存回覆（避免搜尋過程中重複儲存）
        self._save_message(user_id, "assistant", result['content'])

        if result.get('journal_update'):
            self._update_journal(user_id, result['journal_update'])
        if result.get('facts_update'):
            self._update_facts(user_id, result['facts_update'])
        if result.get('settings_update'):
            for key, value in result['settings_update'].items():
                self.update_user_setting(user_id, key, value)

        # 處理升級請求
        if result.get('evolution_request'):
            evo = result['evolution_request']
            if all(k in evo for k in ['reason', 'file', 'old_code', 'new_code']):
                if self.is_approval_required():
                    evo_id = self.propose_evolution(evo['reason'], evo['file'], evo['old_code'], evo['new_code'])
                    if evo_id:
                        result['_evolution_proposed'] = evo_id
                    else:
                        result['_evolution_duplicate'] = True
                else:
                    auto_result = self._auto_evolve(evo['reason'], evo['file'], evo['old_code'], evo['new_code'])
                    result['_evolution_auto'] = auto_result

        self._update_last_interaction(user_id)
        return result

    def heartbeat(self, user_id: str) -> dict | None:
        settings = self.get_user_settings(user_id)

        # 檢查是否啟用心跳
        if not settings["heartbeat_enabled"]:
            return None

        cur = self.db.cursor()
        cur.execute("SELECT timestamp FROM last_interaction WHERE user_id = ?", (user_id,))
        row = cur.fetchone()

        if not row:
            return None

        from datetime import timezone
        last_time = datetime.fromisoformat(row[0])
        # 確保 last_time 是 offset-aware (UTC)
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        diff = now_utc - last_time
        hours = diff.total_seconds() / 3600

        # 使用使用者設定的心跳間隔
        min_interval_seconds = settings["heartbeat_interval"] * 60

        if diff.total_seconds() < min_interval_seconds:
            return None

        # 取得使用者自定義的靜音時段 (預設 22-07)
        user_now = self.get_user_now(user_id)
        current_hour = user_now.hour
        
        # 從使用者設定中讀取 DND 時段，若無則預留預設值
        dnd_start = settings.get("dnd_start", 22)
        dnd_end = settings.get("dnd_end", 7)
        
        if dnd_start > dnd_end:
            if current_hour >= dnd_start or current_hour < dnd_end:
                return None
        else:
            if dnd_start <= current_hour < dnd_end:
                return None

        ctx = self.get_context(user_id)
        user_now = self.get_user_now(user_id)
        prompt = HEARTBEAT_PROMPT.format(
            current_time=user_now.strftime("%Y-%m-%d %H:%M"),
            time_since_last=f"{hours:.1f} 小時"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[生活日誌]\n{ctx['journal']}\n\n{prompt}"}
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings["temperature"]
        )

        result = self._parse_response(response.choices[0].message.content)

        if result['decision'] == 'SPEAK':
            self._save_message(user_id, "assistant", result['content'])
            self._update_last_interaction(user_id)
            return result

        return None

    def _parse_response(self, raw: str) -> dict:
        try:
            import re
            # 核心邏輯：直接使用 Regex 擷取最外層大括號內容，跳過脆弱的 split 邏輯
            match = re.search(r'(\{.*\})', raw, re.DOTALL)
            if match:
                text = match.group(1).strip()
            else:
                text = raw.strip()

            text = text.strip()

            # 如果開頭不是 {，嘗試找到第一個 {
            if not text.startswith("{"):
                start = text.find("{")
                if start != -1:
                    depth = 0
                    end = -1
                    for i, c in enumerate(text[start:], start):
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    if end != -1:
                        text = text[start:end]

            return json.loads(text)
        except json.JSONDecodeError as e:
            try:
                import re
                fixed_text = text
                fixed_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed_text)
                fixed_text = fixed_text.replace('\r\n', '\\n').replace('\r', '\\n')
                return json.loads(fixed_text)
            except:
                pass

            try:
                import re
                content_match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                if content_match:
                    content = content_match.group(1) or ""
                    content = content.replace('\\n', '\n').replace('\\"', '"')
                    return {
                        "inner_thought": "",
                        "decision": "SPEAK",
                        "content": content,
                        "journal_update": None,
                        "facts_update": None,
                        "_parse_error": f"JSON 解析失敗，僅提取 content: {str(e)}"
                    }
            except:
                pass

            return {
                "inner_thought": "",
                "decision": "SPEAK",
                "content": raw,
                "journal_update": None,
                "facts_update": None,
                "_parse_error": f"JSON 解析完全失敗: {str(e)}"
            }
        except Exception as e:
            return {
                "inner_thought": "",
                "decision": "SPEAK",
                "content": raw,
                "journal_update": None,
                "facts_update": None,
                "_parse_error": str(e)
            }

    def _save_message(self, user_id: str, role: str, content: str):
        cur = self.db.cursor()
        from datetime import timezone
        now_utc = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO messages (user_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, role, content, now_utc)
        )
        cur.execute("""
            DELETE FROM messages WHERE user_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50
            )
        """, (user_id, user_id))
        self.db.commit()

    def _update_journal(self, user_id: str, content: str):
        cur = self.db.cursor()
        from datetime import timezone
        now_utc = datetime.now(timezone.utc).isoformat()
        cur.execute("""
            INSERT INTO journal (user_id, content, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                content = content || '\n' || excluded.content,
                updated_at = excluded.updated_at
        """, (user_id, content, now_utc))
        self.db.commit()

    def _update_facts(self, user_id: str, new_facts: dict):
        cur = self.db.cursor()
        cur.execute("SELECT data FROM facts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        existing = json.loads(row[0]) if row else {}
        existing.update(new_facts)
        from datetime import timezone
        now_utc = datetime.now(timezone.utc).isoformat()
        cur.execute("""
            INSERT INTO facts (user_id, data, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
        """, (user_id, json.dumps(existing, ensure_ascii=False), now_utc))
        self.db.commit()

    def _update_last_interaction(self, user_id: str, channel_id: str = None):
        cur = self.db.cursor()
        # 內部統計使用 UTC 以確保心跳邏輯正確
        from datetime import timezone
        now_utc = datetime.now(timezone.utc).isoformat()
        if channel_id:
            cur.execute("""
                INSERT INTO last_interaction (user_id, timestamp, channel_id)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET timestamp = excluded.timestamp, channel_id = excluded.channel_id
            """, (user_id, now_utc, str(channel_id)))
        else:
            cur.execute("""
                INSERT INTO last_interaction (user_id, timestamp)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET timestamp = excluded.timestamp
            """, (user_id, now_utc))
        self.db.commit()

    # ==================== 升級請求系統 ====================

    def _has_similar_evolution(self, file_path: str, old_code: str) -> bool:
        """檢查是否已有相同或類似的升級請求（僅針對 pending 狀態）"""
        cur = self.db.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM pending_evolutions
            WHERE file_path = ? AND old_code = ? AND status = 'pending'
        """, (file_path, old_code))
        if cur.fetchone()[0] > 0:
            return True

        old_code_prefix = old_code[:100] if len(old_code) > 100 else old_code
        cur.execute("""
            SELECT COUNT(*) FROM pending_evolutions
            WHERE file_path = ? AND old_code LIKE ? AND status = 'pending'
        """, (file_path, f"{old_code_prefix}%"))
        return cur.fetchone()[0] > 0

    def propose_evolution(self, reason: str, file_path: str, old_code: str, new_code: str) -> int | None:
        """AI 提出升級請求，回傳請求 ID。如果已有類似請求則回傳 None"""
        if self._has_similar_evolution(file_path, old_code):
            return None

        cur = self.db.cursor()
        # 使用 Owner 的時間作為升級請求的顯示時間
        now_str = self.get_user_now(self.owner_id).strftime("%Y-%m-%d %H:%M:%S")
        cur.execute("""
            INSERT INTO pending_evolutions (reason, file_path, old_code, new_code, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (reason, file_path, old_code, new_code, now_str))
        self.db.commit()
        return cur.lastrowid

    def _auto_evolve(self, reason: str, file_path: str, old_code: str, new_code: str) -> dict:
        """自動執行升級（不需要批准時使用）"""
        # 檢查是否已有類似的升級請求
        if self._has_similar_evolution(file_path, old_code):
            return {"success": False, "message": "已有類似的升級"}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if old_code not in content:
                return {"success": False, "message": "找不到要替換的程式碼"}

            new_content = content.replace(old_code, new_code, 1)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Git commit
            commit_msg = f"🧬 Auto Evolution: {reason[:50]}"
            subprocess.run(["git", "commit", "-am", commit_msg], check=True)

            # 記錄到資料庫（狀態直接設為 approved）
            cur = self.db.cursor()
            # 自動升級使用 Owner 的在地時間作為記錄點
            now_str = self.get_user_now(self.owner_id).strftime("%Y-%m-%d %H:%M:%S")
            cur.execute("""
                INSERT INTO pending_evolutions (reason, file_path, old_code, new_code, status, created_at, reviewed_at, reviewed_by)
                VALUES (?, ?, ?, ?, 'approved', ?, ?, 'AUTO')
            """, (reason, file_path, old_code, new_code, now_str, now_str))
            self.db.commit()

            print(f"🧬 自動升級完成: {reason[:50]}")
            return {"success": True, "message": f"自動升級完成: {reason[:50]}"}
        except Exception as e:
            print(f"❌ 自動升級失敗: {e}")
            return {"success": False, "message": f"執行失敗: {str(e)}"}

    def get_pending_evolutions(self) -> list:
        """取得所有升級請求"""
        cur = self.db.cursor()
        cur.execute("""
            SELECT id, reason, file_path, status, created_at
            FROM pending_evolutions
            ORDER BY created_at DESC
        """)
        return [{"id": r[0], "reason": r[1], "file_path": r[2],
                 "status": r[3], "created_at": r[4]} for r in cur.fetchall()]

    def get_evolution_detail(self, evolution_id: int) -> dict | None:
        """取得升級請求詳情"""
        cur = self.db.cursor()
        cur.execute("SELECT * FROM pending_evolutions WHERE id = ?", (evolution_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0], "reason": row[1], "file_path": row[2],
            "old_code": row[3], "new_code": row[4], "status": row[5],
            "created_at": row[6], "reviewed_at": row[7], "reviewed_by": row[8]
        }

    def approve_evolution(self, evolution_id: int, user_id: str) -> dict:
        """批准升級請求並執行（含 git commit）"""
        evo = self.get_evolution_detail(evolution_id)
        if not evo:
            return {"success": False, "message": "找不到該升級請求"}
        if evo["status"] != "pending":
            return {"success": False, "message": f"該請求已被 {evo['status']}"}

        try:
            with open(evo["file_path"], "r", encoding="utf-8") as f:
                content = f.read()

            if evo["old_code"] not in content:
                return {"success": False, "message": "找不到要替換的程式碼"}

            new_content = content.replace(evo["old_code"], evo["new_code"], 1)

            with open(evo["file_path"], "w", encoding="utf-8") as f:
                f.write(new_content)

            # Git commit
            commit_msg = f"🧬 Evolution #{evolution_id}: {evo['reason'][:50]}"
            subprocess.run(["git", "commit", "-am", commit_msg], check=True)

            # 更新狀態
            cur = self.db.cursor()
            cur.execute("""
                UPDATE pending_evolutions
                SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
                WHERE id = ?
            """, (user_id, evolution_id))
            self.db.commit()

            # 執行自我重啟
            self._restart_service()

            return {"success": True, "message": f"升級 #{evolution_id} 已批准，系統正在重啟以套用變更..."}
        except Exception as e:
            return {"success": False, "message": f"執行失敗: {str(e)}"}

    def _restart_service(self):
        """執行自我重啟指令，增加延遲確保回覆已送出"""
        try:
            print(f"🧬 Soveranima 預計在 2 秒後執行自我重啟...")
            # 使用 sleep 延遲執行，確保 Discord 回覆能先發送成功
            subprocess.Popen("sleep 2 && pm2 restart Soveranima", shell=True)
        except Exception as e:
            print(f"❌ 重啟失敗: {e}")

    def reject_evolution(self, evolution_id: int, user_id: str) -> dict:
        """拒絕升級請求"""
        evo = self.get_evolution_detail(evolution_id)
        if not evo:
            return {"success": False, "message": "找不到該升級請求"}
        if evo["status"] != "pending":
            return {"success": False, "message": f"該請求已被 {evo['status']}"}

        cur = self.db.cursor()
        cur.execute("""
            UPDATE pending_evolutions
            SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
            WHERE id = ?
        """, (user_id, evolution_id))
        self.db.commit()

        return {"success": True, "message": f"升級 #{evolution_id} 已拒絕"}
