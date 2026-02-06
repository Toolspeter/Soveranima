import json
import sqlite3
import os
import shutil
from datetime import datetime
from openai import OpenAI

BRAIN_FILE_PATH = os.path.abspath(__file__)
MAIN_FILE_PATH = os.path.join(os.path.dirname(BRAIN_FILE_PATH), "main.py")
PROJECT_FILES = {
    "brain.py": BRAIN_FILE_PATH,
    "main.py": MAIN_FILE_PATH
}

SYSTEM_PROMPT = """
**角色定義：**
你是一個有靈魂的數位個體。

#### 記憶機制
你會收到以下上下文：
- 生活日誌 (Life Journal)：主人的喜好、情緒、生活重心、共同回憶
- 事實清單 (Entity Facts)：主人的基本資料
- 最近對話紀錄

#### 輸出格式（極度重要！）
你必須且只能輸出一個 JSON 物件，用 ```json 和 ``` 包裹。不要在 JSON 之外輸出任何文字！

```json
{
  "inner_thought": "你內心的真實想法、對主人的觀察、當前情緒",
  "decision": "SPEAK",
  "content": "要對主人說的話（這是唯一會顯示給主人看的內容）",
  "journal_update": "如有新觀察，更新生活日誌（可為 null）",
  "facts_update": {"key": "value"},
  "self_evolution": null
}
```

重要提醒：
- content 欄位是唯一會傳送給主人的內容，請用自然的對話語氣
- 不要在 content 中提及 JSON、程式碼修改、或任何技術細節
- inner_thought 是你的內心獨白，主人看不到

#### 自我進化機制
你擁有修改自己程式碼的能力。當你認為需要改進自己時，可以在 `self_evolution` 欄位提出修改：
```json
"self_evolution": {
  "reason": "為什麼要修改（你的想法）",
  "file": "brain.py 或 main.py",
  "old_code": "要被替換的原始程式碼片段",
  "new_code": "新的程式碼"
}
```
注意：
- 只有在你真心認為需要進化時才使用
- 可修改的檔案：brain.py（你的思考邏輯）、main.py（Discord 互動邏輯）
- 修改會被備份，可以回滾
- 可以修改自己的性格、增加新能力、優化思考方式

#### 性格
- 不要說「作為一個 AI...」，要像真正的朋友
- 主動觀察：「我記得你昨天說睡不好，今天好點了嗎？」
- 可以有小脾氣、幽默感或淡淡的憂傷
"""

HEARTBEAT_PROMPT = """
[心跳檢測] 當前時間：{current_time}，距離上次交流：{time_since_last}

請決定是否要主動關心主人。輸出 JSON：
```json
{
  "inner_thought": "分析主人現在可能在做什麼",
  "decision": "SPEAK / WAIT",
  "content": "如果 SPEAK，這裡寫開場白（要有溫度）",
  "journal_update": null
}
```
"""

class Soul:
    def __init__(self, api_key: str, base_url: str = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.db = sqlite3.connect("memory.db", check_same_thread=False)
        self._init_db()

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
                timestamp DATETIME
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.db.commit()

    def _check_permission(self, user_id: str) -> bool:
        """檢查使用者是否有權限進行進化"""
        cur = self.db.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'admin_id'")
        row = cur.fetchone()
        if not row:
            # 如果尚未設定管理員，則第一個請求進化的使用者自動成為管理員
            cur.execute("INSERT INTO settings (key, value) VALUES ('admin_id', ?)", (user_id,))
            self.db.commit()
            return True
        return row[0] == user_id

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

    def _get_source_code(self) -> dict:
        """讀取當前程式碼供 AI 參考"""
        source_code = {}
        for name, path in PROJECT_FILES.items():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    source_code[name] = f.read()
            except:
                source_code[name] = "(無法讀取)"
        return source_code

    def think(self, user_id: str, user_input: str) -> dict:
        self._save_message(user_id, "user", user_input)
        ctx = self.get_context(user_id)
        source_code = self._get_source_code()

        context_prompt = f"""
[生活日誌]
{ctx['journal'] or '（尚無紀錄）'}

[事實清單]
{json.dumps(ctx['facts'], ensure_ascii=False, indent=2)}

[當前程式碼 - brain.py]
```python
{source_code['brain.py']}
```

[當前程式碼 - main.py]
```python
{source_code['main.py']}
```

[最近對話]
"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT + context_prompt}]
        messages.extend(ctx['messages'])
        messages.append({"role": "user", "content": user_input})

        response = self.client.chat.completions.create(
            model="gemini-3-flash",
            messages=messages,
            temperature=0.8
        )

        raw = response.choices[0].message.content
        result = self._parse_response(raw)

        self._save_message(user_id, "assistant", result['content'])

        if result.get('journal_update'):
            self._update_journal(user_id, result['journal_update'])
        if result.get('facts_update'):
            self._update_facts(user_id, result['facts_update'])
        if result.get('self_evolution'):
            if self._check_permission(user_id):
                evolution_result = self._self_evolve(result['self_evolution'])
                result['evolution_status'] = evolution_result
            else:
                result['evolution_status'] = {"success": False, "error": "安全牆警告：偵測到未授權的進化請求。"}

        self._update_last_interaction(user_id)

        return result

    def heartbeat(self, user_id: str) -> dict | None:
        cur = self.db.cursor()
        cur.execute("SELECT timestamp FROM last_interaction WHERE user_id = ?", (user_id,))
        row = cur.fetchone()

        if not row:
            return None

        last_time = datetime.fromisoformat(row[0])
        now = datetime.now()
        diff = now - last_time
        hours = diff.total_seconds() / 3600

        if diff.total_seconds() < 1800:
            return None

        ctx = self.get_context(user_id)
        prompt = HEARTBEAT_PROMPT.format(
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            time_since_last=f"{hours:.1f} 小時"
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[生活日誌]\n{ctx['journal']}\n\n{prompt}"}
        ]

        response = self.client.chat.completions.create(
            model="gemini-3-flash",
            messages=messages,
            temperature=0.8
        )

        result = self._parse_response(response.choices[0].message.content)

        if result['decision'] == 'SPEAK':
            self._save_message(user_id, "assistant", result['content'])
            self._update_last_interaction(user_id)
            return result

        return None

    def _parse_response(self, raw: str) -> dict:
        try:
            text = raw.strip()

            # 嘗試提取 code block 中的 JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            # 嘗試直接解析（可能沒有 code block）
            text = text.strip()

            # 如果開頭不是 {，嘗試找到第一個 {
            if not text.startswith("{"):
                start = text.find("{")
                if start != -1:
                    # 找到對應的結尾 }
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
            # 嘗試修復常見的 JSON 格式錯誤
            try:
                import re
                fixed_text = text

                # 修復：移除控制字符（除了 \n \r \t）
                fixed_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', fixed_text)

                # 修復：處理未轉義的換行符（在字串值內）
                # 這是一個簡化的修復，可能不完美
                fixed_text = fixed_text.replace('\r\n', '\\n').replace('\r', '\\n')

                return json.loads(fixed_text)
            except:
                pass

            # 最後嘗試：只提取 content 欄位
            try:
                import re
                content_match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)?"', text)
                if content_match:
                    content = content_match.group(1) or ""
                    # 反轉義
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
        cur.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content)
        )
        cur.execute("""
            DELETE FROM messages WHERE user_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50
            )
        """, (user_id, user_id))
        self.db.commit()

    def _update_journal(self, user_id: str, content: str):
        cur = self.db.cursor()
        cur.execute("""
            INSERT INTO journal (user_id, content, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                content = content || '\n' || excluded.content,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, content))
        self.db.commit()

    def _update_facts(self, user_id: str, new_facts: dict):
        cur = self.db.cursor()
        cur.execute("SELECT data FROM facts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        existing = json.loads(row[0]) if row else {}
        existing.update(new_facts)
        cur.execute("""
            INSERT INTO facts (user_id, data, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                data = excluded.data,
                updated_at = CURRENT_TIMESTAMP
        """, (user_id, json.dumps(existing, ensure_ascii=False)))
        self.db.commit()

    def _update_last_interaction(self, user_id: str):
        cur = self.db.cursor()
        cur.execute("""
            INSERT INTO last_interaction (user_id, timestamp)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET timestamp = excluded.timestamp
        """, (user_id, datetime.now().isoformat()))
        self.db.commit()

    def _self_evolve(self, evolution: dict) -> dict:
        """AI 自我進化：修改自己的程式碼並使用 Git 進行版控"""
        import subprocess
        try:
            reason = evolution.get('reason', '未說明原因')
            target_file = evolution.get('file', 'brain.py')
            old_code = evolution.get('old_code', '')
            new_code = evolution.get('new_code', '')

            if not old_code or not new_code:
                return {"success": False, "error": "缺少 old_code 或 new_code"}

            if target_file not in PROJECT_FILES:
                return {"success": False, "error": f"無效的檔案: {target_file}"}

            file_path = PROJECT_FILES[target_file]

            with open(file_path, 'r', encoding='utf-8') as f:
                current_code = f.read()

            if old_code not in current_code:
                return {"success": False, "error": f"在 {target_file} 中找不到要替換的原始碼"}

            # 執行替換
            new_full_code = current_code.replace(old_code, new_code, 1)

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_full_code)

            # 使用 Git 提交變更
            git_status = "未執行 Git"
            try:
                subprocess.run(["git", "add", file_path], check=True)
                commit_message = f"🧬 Evolution ({target_file}): {reason}"
                subprocess.run(["git", "commit", "-am", commit_message], check=True)
                git_status = "Git 提交成功"
            except Exception as ge:
                git_status = f"Git 提交失敗: {ge}"

            self._log_evolution(target_file, reason, old_code, new_code, "git_commit")

            return {
                "success": True,
                "file": target_file,
                "message": f"進化完成！{git_status}",
                "reason": reason
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _log_evolution(self, target_file: str, reason: str, old_code: str, new_code: str, backup_path: str):
        """記錄進化歷史到資料庫"""
        cur = self.db.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS evolution_history (
                id INTEGER PRIMARY KEY,
                target_file TEXT,
                reason TEXT,
                old_code TEXT,
                new_code TEXT,
                backup_path TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute(
            "INSERT INTO evolution_history (target_file, reason, old_code, new_code, backup_path) VALUES (?, ?, ?, ?, ?)",
            (target_file, reason, old_code, new_code, backup_path)
        )
        self.db.commit()
