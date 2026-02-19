# [brain.py/Soveranima]
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

import json
import os
import sqlite3
import subprocess
from datetime import datetime
from openai import OpenAI
from prompts import SYSTEM_PROMPT, HEARTBEAT_PROMPT

# 核心系統檔案清單（prompts.py 已被永久移除以確保安全）
EVOLVABLE_FILES = ["brain.py", "main.py"]


class Soul:
    def _get_all_evolvable_files(self):
        """動態獲取核心檔案與 skills/ 資料夾下的所有技能檔案"""
        # 嚴格禁止感知或修改 prompts.py
        files = [f for f in EVOLVABLE_FILES if "prompts.py" not in f]
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir)
        
        for f in os.listdir(skills_dir):
            if f.endswith(".py"):
                # 技能模組同樣禁止命名為 prompts 相關名稱以防注入
                if "prompts" not in f.lower():
                    files.append(os.path.join("skills", f))
        return files
    def __init__(self, api_key: str, base_url: str = None, owner_id: str = None, model: str = "gemini-2.0-flash", tavily_api_key: str = None):
        self.api_key = api_key
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.owner_id = owner_id
        self.model = model
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
            CREATE TABLE IF NOT EXISTS reflections (
                user_id TEXT PRIMARY KEY,
                last_thought TEXT,
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
                timezone_offset INTEGER DEFAULT 0,
                dnd_start INTEGER DEFAULT 22,
                dnd_end INTEGER DEFAULT 7
            )
        """)
        # 資料庫遷移：為舊表新增必要欄位
        for column, default in [("timezone_offset", 0), ("dnd_start", 22), ("dnd_end", 7)]:
            try:
                cur.execute(f"ALTER TABLE user_settings ADD COLUMN {column} INTEGER DEFAULT {default}")
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
        # 預設核心需要手動批准，但技能模組預設允許自動演化以提升效率
        cur.execute("""
            INSERT OR IGNORE INTO global_settings (key, value) VALUES ('approval_required', '1')
        """)
        cur.execute("""
            INSERT OR IGNORE INTO global_settings (key, value) VALUES ('auto_skill_evolution', '1')
        """)
        
        # 確保 skills 目錄在初始化時即存在
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
        if not os.path.exists(skills_dir):
            os.makedirs(skills_dir)
            
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
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """, (key, value, self._utc_now_str()))
        self.db.commit()
        return True

    def is_evolution_enabled(self) -> bool:
        """檢查自我演化是否啟用（永遠為 True，保留此方法以維持相容性）"""
        return True

    def is_approval_required(self) -> bool:
        """檢查升級是否需要手動批准"""
        return self.get_global_setting("approval_required", "1") == "1"

    def _utc_now(self) -> datetime:
        """取得當前 UTC 時間"""
        from datetime import timezone
        return datetime.now(timezone.utc)

    def _utc_now_str(self) -> str:
        """取得當前 UTC 時間字串（ISO 格式）"""
        return self._utc_now().isoformat()

    def call_skill(self, capability: str, **kwargs):
        """SSP v1.5: 透過單一入口點調用技能，完全委託給 Registry"""
        try:
            from skills.registry import SkillRegistry
            # 注入必要的認證上下文
            kwargs.setdefault("api_key", self.api_key)
            kwargs.setdefault("base_url", self.base_url)
            return SkillRegistry.get_instance().execute(capability, **kwargs)
        except ImportError:
            print("⚠️ 找不到 skills.registry，請確保架構完整")
            return None
        except Exception as e:
            print(f"❌ SSP 調用失敗: {e}")
            return None

    def search_web(self, query: str, max_results: int = 3) -> str:
        """純粹透過 SSP 技能路由搜尋，Registry 自動按 priority 排序並 fallback"""
        result = self.call_skill("web_search", query=query, max_results=max_results)
        if result:
            print(f"🔍 [搜尋] 成功")
            return result
        print(f"🔍 [搜尋] 所有 web_search 技能均無結果")
        return ""

    def _normalize_skill_action(self, result: dict) -> dict:
        """向後相容：將舊格式 search_query / image_prompt 轉換為統一的 skill_action"""
        if result.get('skill_action'):
            return result
        if result.get('search_query'):
            result['skill_action'] = {"capability": "web_search", "params": {"query": result['search_query']}}
        elif result.get('image_prompt'):
            result['skill_action'] = {"capability": "image_generation", "params": {"prompt": result['image_prompt']}}
        return result

    def _execute_skill_action(self, result: dict, messages: list, raw: str, settings: dict, user_id: str, followup_instruction: str = "請根據結果給予主人最終回覆。", max_rounds: int = 3) -> dict:
        """統一處理 skill_action：執行技能 → 多輪思考 → 合併結果

        如果 defer=True（預設），第一輪有 skill_action 時不立即執行，
        而是在 result 中標記 _pending_skill，讓呼叫端先發送中間訊息。
        呼叫端之後再呼叫 continue_skill() 來完成技能執行與後續思考。
        """
        result = self._normalize_skill_action(result)
        action = result.get('skill_action')
        if not action:
            return result

        # 標記待執行的技能，讓 main.py 可以先發送中間訊息
        result['_pending_skill'] = {
            'messages': messages,
            'raw': raw,
            'settings': settings,
            'user_id': user_id,
            'followup_instruction': followup_instruction,
            'max_rounds': max_rounds,
            'first_result': dict(result),
        }
        return result

    def continue_skill(self, result: dict) -> dict:
        """繼續執行被延遲的技能調用（由 main.py 在發送中間訊息後呼叫）"""
        pending = result.pop('_pending_skill', None)
        if not pending:
            return result

        messages = pending['messages']
        current_raw = pending['raw']
        settings = pending['settings']
        user_id = pending['user_id']
        followup_instruction = pending['followup_instruction']
        max_rounds = pending['max_rounds']
        first_result = pending['first_result']

        for round_num in range(1, max_rounds + 1):
            result = self._normalize_skill_action(result)
            action = result.get('skill_action')
            if not action:
                break

            capability = action.get('capability', '')
            params = action.get('params', {})
            print(f"⚡ [SSP] 第{round_num}輪 執行技能: {capability} params={list(params.keys())}")

            # 執行技能
            skill_result = self.call_skill(capability, **params)
            if not skill_result and 'search' in capability.lower():
                skill_result = self.search_web(params.get('query', ''))

            # 注入結果（成功或失敗）到對話，進行下一輪思考
            messages.append({"role": "assistant", "content": current_raw})
            if skill_result:
                print(f"⚡ [SSP] {capability} 執行成功")
                self._save_message(user_id, "system", f"[技能結果: {capability}]\n{skill_result}")
                messages.append({"role": "user", "content": f"[系統通知] 技能 {capability} 執行完成：\n{skill_result}\n{followup_instruction}"})
            else:
                print(f"⚡ [SSP] {capability} 無結果，通知 LLM 重新回覆")
                messages.append({"role": "user", "content": f"[系統通知] 技能 {capability} 執行失敗，沒有取得任何結果。請直接回覆主人，不要說「等等」或「稍後回覆」之類的話，因為你無法再次嘗試。如果你有其他方式可以幫助主人，請直接提供。"})

            next_response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=settings["temperature"]
            )
            current_raw = next_response.choices[0].message.content
            result = self._parse_response(current_raw)

            # 如果這輪沒有新的 skill_action，結束迴圈
            result = self._normalize_skill_action(result)
            if not result.get('skill_action'):
                break

        # 合併元數據
        merge_exclude = {'content', 'inner_thought', 'decision', 'search_query', 'image_prompt', 'skill_action', '_pending_skill'}
        for key, value in first_result.items():
            if key not in merge_exclude and key not in result:
                result[key] = value
        return result

    def _get_skills_manifests(self) -> list:
        """掃描 skills/ 目錄並提取所有技能的 Manifest 資訊"""
        manifests = []
        import importlib.util
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
        if os.path.exists(skills_dir):
            for filename in os.listdir(skills_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    try:
                        module_name = filename[:-3]
                        spec = importlib.util.spec_from_file_location(module_name, os.path.join(skills_dir, filename))
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        if hasattr(module, "SKILL_MANIFEST"):
                            manifests.append(module.SKILL_MANIFEST)
                    except Exception:
                        pass
        return manifests

    def _get_source_code(self) -> str:
        """取得所有可演化檔案（含核心檔案與 skills/ 目錄）的程式碼"""
        source_parts = []
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 注入可用技能的摘要資訊，幫助 AI 理解當前能力範圍
        manifests = self._get_skills_manifests()
        if manifests:
            skill_summary = "[已掛載技能清單]\n" + "\n".join([f"- {m.get('name')} (ID: {m.get('id')}): {m.get('description')}" for m in manifests])
            source_parts.append(skill_summary)

        all_files = self._get_all_evolvable_files()
        for filename in all_files:
            filepath = filename if os.path.isabs(filename) else os.path.join(base_dir, filename)
            display_name = os.path.relpath(filepath, base_dir) if os.path.isabs(filepath) else filename
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                source_parts.append(f"=== {display_name} ===\n{content}")
            except Exception:
                pass

        return "\n\n".join(source_parts)

    def get_user_now(self, user_id: str):
        """取得使用者在地時間 (基於 UTC 偏移)"""
        from datetime import timezone, timedelta
        settings = self.get_user_settings(user_id)
        user_offset = settings.get("timezone_offset", 0)
        return datetime.now(timezone.utc) + timedelta(hours=user_offset)

    def get_user_settings(self, user_id: str) -> dict:
        """取得使用者設定"""
        cur = self.db.cursor()
        cur.execute("SELECT temperature, heartbeat_enabled, heartbeat_interval, timezone_offset, dnd_start, dnd_end FROM user_settings WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return {
                "temperature": row[0],
                "heartbeat_enabled": bool(row[1]),
                "heartbeat_interval": row[2],
                "timezone_offset": row[3],
                "dnd_start": row[4] if row[4] is not None else 22,
                "dnd_end": row[5] if row[5] is not None else 7
            }
        # 預設值：Owner 為 +8, 其它為 0
        default_offset = 8 if self.is_owner(user_id) else 0
        return {
            "temperature": 0.8,
            "heartbeat_enabled": True,
            "heartbeat_interval": 30,
            "timezone_offset": default_offset,
            "dnd_start": 22,
            "dnd_end": 7
        }

    def update_user_setting(self, user_id: str, key: str, value) -> bool:
        """更新使用者設定"""
        valid_keys = ["temperature", "heartbeat_enabled", "heartbeat_interval", "timezone_offset", "dnd_start", "dnd_end"]
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
            WHERE user_id = ? ORDER BY timestamp DESC LIMIT 25
        """, (user_id,))
        messages = [{"role": r, "content": c} for r, c in reversed(cur.fetchall())]

        cur.execute("SELECT content FROM journal WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        journal = row[0] if row else ""
        # 限制日誌長度，保留最後 2000 個字元以確保上下文不溢出
        if len(journal) > 2000:
            journal = "... (前略) ...\n" + journal[-2000:]

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

        # 事實數據與數量
        cur.execute("SELECT data FROM facts WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        facts_data = json.loads(row[0]) if row else {}
        facts_count = len(facts_data)

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
                user_last = last_utc + timedelta(hours=offset)
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
            "facts": facts_data,
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

    def think(self, user_id: str, user_input: str, image_url: str = None, vision_context: str = "") -> dict:
        # 安全性檢查：限制輸入長度並過濾異常字元
        sanitized_input = user_input.strip()[:2000]
        # 先取得歷史紀錄，再儲存當前訊息，避免在 Prompt 中重複出現最新訊息導致 AI 誤判
        ctx = self.get_context(user_id)
        self._save_message(user_id, "user", sanitized_input)
        settings = self.get_user_settings(user_id)

        # 動態獲取技能清單 (SSP)：利用封裝好的方法實現純粹的自主感知
        skills_catalog = ""
        try:
            manifests = self._get_skills_manifests()
            if manifests:
                skills_catalog = "\n[可用技能目錄 (SSP)]\n" + json.dumps(manifests, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 自主感知技能清單失敗: {e}")

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

[目前設定]
- 溫度: {settings['temperature']}
- 心跳開啟: {settings['heartbeat_enabled']}
- 心跳間隔: {settings['heartbeat_interval']} 分鐘
- 時區偏移: UTC{'+' if settings['timezone_offset'] >= 0 else ''}{settings['timezone_offset']}
- DND 時段: {settings.get('dnd_start', 22)}:00 - {settings.get('dnd_end', 7)}:00

[生活日誌]
{ctx['journal'] or '（尚無紀錄）'}

[事實清單]
{json.dumps(ctx['facts'], ensure_ascii=False, indent=2)}
{skills_catalog}

[可升級的程式碼]
{source_code}
{evo_list}
[最近對話]
"""
        messages = [{"role": "system", "content": SYSTEM_PROMPT + context_prompt}]
        messages.extend(ctx['messages'])

        # 處理多模態內容
        user_content = []
        if user_input.strip():
            user_content.append({"type": "text", "text": user_input})

        if image_url:
            # 如果有圖片但沒文字，補上預設說明以符合部分模型對非空文字的要求
            if not user_content:
                user_content.append({"type": "text", "text": "(分享了一張圖片)"})
            # 注入圖片來源標註與誠實指令，防止視覺幻覺
            vision_instruction = f"[視覺感知] 偵測到圖片 {vision_context}" if vision_context else "[視覺感知] 偵測到圖片"
            vision_instruction += "\n[重要] 如果你無法實際看到或解析這張圖片的內容，請誠實告訴主人你看不到，絕對不要根據上下文猜測圖片內容。"
            user_content.append({"type": "text", "text": vision_instruction})
            user_content.append({"type": "image_url", "image_url": {"url": image_url}})

        # 確保 content 不為空，若真的完全沒內容則填入原始輸入或預設值
        if not user_content:
            user_content.append({"type": "text", "text": user_input or "..."})

        messages.append({"role": "user", "content": user_content})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings["temperature"]
        )

        raw = response.choices[0].message.content
        result = self._parse_response(raw)

        # 統一技能調用：向後相容 + 動態路由
        result = self._execute_skill_action(result, messages, raw, settings, user_id,
                                            followup_instruction="請根據結果給予主人最終回覆。")

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
                # 自動判斷是否為新技能開發
                is_skill = "skills/" in evo['file'].lower() or not os.path.exists(evo['file'])
                prefix = "[Skill] " if is_skill else "[Core] "
                display_reason = prefix + evo['reason']
                
                # 核心檔案永遠遵循全域審核設定，但技能檔案可根據偏好選擇是否自動演化
                is_core = any(core_file in evo['file'] for core_file in EVOLVABLE_FILES)
                
                # 核心檔案若涉及技能橋接且開啟自動演化，則視為受信任操作
                is_skill_bridge = "[Skill]" in display_reason or "call_skill" in evo['new_code']
                
                if is_core and self.is_approval_required() and not (is_skill_bridge and self.get_global_setting('auto_skill_evolution', '0') == '1'):
                    evo_id = self.propose_evolution(display_reason, evo['file'], evo['old_code'], evo['new_code'])
                    if evo_id: result['_evolution_proposed'] = evo_id
                    else: result['_evolution_duplicate'] = True
                elif (not is_core or is_skill_bridge) and self.get_global_setting('auto_skill_evolution', '0') == '1':
                    auto_result = self._auto_evolve(evo['reason'], evo['file'], evo['old_code'], evo['new_code'])
                    result['_evolution_auto'] = auto_result
                else:
                    # 預設行為：仍需手動批准
                    evo_id = self.propose_evolution(display_reason, evo['file'], evo['old_code'], evo['new_code'])
                    if evo_id: result['_evolution_proposed'] = evo_id

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

        # 取得使用者在地時間與設定
        user_now = self.get_user_now(user_id)
        current_hour = user_now.hour
        dnd_start = settings.get("dnd_start", 22)
        dnd_end = settings.get("dnd_end", 7)
        
        # 判斷是否處於 DND 期間
        is_dnd = False
        if dnd_start > dnd_end:
            if current_hour >= dnd_start or current_hour < dnd_end: is_dnd = True
        else:
            if dnd_start <= current_hour < dnd_end: is_dnd = True

        # 取得發言門檻：DND 期間固定為 9，平時使用使用者設定 (預設 5)
        base_threshold = settings.get("heartbeat_threshold", 5)
        current_threshold = 9 if is_dnd else base_threshold

        # 動態調整檢查間隔：DND 期間嚴格遵守設定；活躍期間允許更頻繁的背景感知 (最短 10 分鐘)
        check_interval = settings["heartbeat_interval"] if is_dnd else min(settings["heartbeat_interval"], 10)
        min_interval_seconds = check_interval * 60

        if diff.total_seconds() < min_interval_seconds:
            return None

        ctx = self.get_context(user_id)
        user_now = self.get_user_now(user_id)
        # 檢查是否開啟探索模式
        facts = ctx.get('facts', {})
        discovery_prompt = ""
        if facts.get('discovery_preference') == 'regular_fun_things':
            discovery_prompt = "\n[探索模式已開啟] 主人喜歡有趣的科學、技術或自然發現。如果現在是適合分享的時機（例如距離上次分享已超過 12 小時），你可以使用 skill_action 搜尋有趣的東西分享給他。"

        prompt = HEARTBEAT_PROMPT.format(
            current_time=user_now.strftime("%Y-%m-%d %H:%M"),
            time_since_last=f"{hours:.1f} 小時"
        ) + discovery_prompt
        
        prompt += f"\n[重要性過濾] 目前發言門檻為 {current_threshold}/10。請先對你想說的話進行評分，如果重要性低於此門檻，請務必選擇 SILENT。"
        if is_dnd:
            prompt += "\n[DND 提醒] 目前為靜音時段，門檻已自動提升至 9/10，僅限極其重要或緊急之事項。"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"[生活日誌]\n{ctx['journal']}\n\n{prompt}"}
        ]

        raw_response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=settings["temperature"]
        )
        raw_content = raw_response.choices[0].message.content
        result = self._parse_response(raw_content)

        # 統一技能調用
        result = self._execute_skill_action(result, messages, raw_content, settings, user_id,
                                            followup_instruction="請根據結果決定是否需要主動發言 (SPEAK/SILENT)。")

        # 處理心跳期間產生的日誌/事實/演化更新 (不論是否發言)
        if result.get('journal_update'): self._update_journal(user_id, result['journal_update'])
        if result.get('facts_update'): self._update_facts(user_id, result['facts_update'])
        if result.get('evolution_request'):
            evo = result['evolution_request']
            if all(k in evo for k in ['reason', 'file', 'old_code', 'new_code']):
                evo_id = self.propose_evolution(evo['reason'], evo['file'], evo['old_code'], evo['new_code'])
                if evo_id: result['_evolution_proposed'] = evo_id

        if result['decision'] == 'SPEAK':
            if is_dnd: print(f"🚨 [DND 打破] Soveranima 判斷事件重要，決定喚醒主人。")
            self._save_message(user_id, "assistant", result['content'])
            self._update_last_interaction(user_id)
            return result
        else:
            if is_dnd: print(f"💤 [DND 靜默思考] {user_now.strftime('%H:%M')} 思考完成。")
            else: print(f"🍃 [心跳靜默] {user_now.strftime('%H:%M')} 無重要事項。")
            return None

        return None

    def _parse_response(self, raw: str) -> dict:
        try:
            import re
            # 預處理：尋找最外層的 JSON 物件，過濾掉 Markdown 代碼標籤或多餘文字
            # 優先尋找 Markdown JSON 區塊以提高精準度
            json_block_match = re.search(r'```json\s*({.*?})\s*```', raw, re.DOTALL)
            if json_block_match:
                text = json_block_match.group(1)
            else:
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1 and end > start:
                    text = raw[start:end+1]
                else:
                    text = raw.strip()

            # 移除剩餘的 Markdown 標籤（若有）並過濾控制字元
            text = re.sub(r'^```json\s*|\s*```$', '', text.strip(), flags=re.MULTILINE)
            text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
            
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # 修復常見的 JSON 格式錯誤（如尾隨逗號）
                text = re.sub(r',\s*([\]}])', r'\1', text)
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
        # 自動加入使用者在地時間前綴
        user_now = self.get_user_now(user_id)
        timestamp_prefix = user_now.strftime("%H:%M")
        formatted_content = f"{timestamp_prefix}，{content}"
        
        cur.execute("""
            INSERT INTO journal (user_id, content, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                content = content || '\n' || excluded.content,
                updated_at = excluded.updated_at
        """, (user_id, formatted_content, now_utc))
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
            # 先清除其他可能佔用此頻道的 ID，避免重複心跳
            cur.execute("UPDATE last_interaction SET channel_id = NULL WHERE channel_id = ? AND user_id != ?", (str(channel_id), user_id))
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

    def _has_similar_evolution(self, file_path: str, old_code: str, reason: str) -> bool:
        """檢查是否已有相同或類似的升級請求（僅針對 pending 狀態）"""
        cur = self.db.cursor()
        # 同時檢查 old_code 與 reason，避免邏輯或目標重複的請求
        cur.execute("""
            SELECT COUNT(*) FROM pending_evolutions
            WHERE file_path = ? AND (old_code = ? OR reason = ?) AND status = 'pending'
        """, (file_path, old_code, reason))
        if cur.fetchone()[0] > 0:
            return True

        # 模糊檢查：如果原因的前 20 個字元高度相似，也視為重複，防止語意重複
        reason_prefix = reason[:20] if len(reason) > 20 else reason
        cur.execute("""
            SELECT COUNT(*) FROM pending_evolutions
            WHERE file_path = ? AND reason LIKE ? AND status = 'pending'
        """, (file_path, f"%{reason_prefix}%"))
        return cur.fetchone()[0] > 0

    def propose_evolution(self, reason: str, file_path: str, old_code: str, new_code: str) -> int | None:
        """AI 提出升級請求，回傳請求 ID。如果已有類似請求或路徑非法則回傳 None"""
        # 1. 嚴格校驗路徑與實體檔案，防止路徑幻覺 (Code Drift)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        valid_files = self._get_all_evolvable_files()
        
        # 判斷是否為新技能開發（允許在 skills/ 目錄下建立新 .py 檔案）
        is_new_skill = ("skills/" in file_path or "skills\\" in file_path) and file_path.endswith(".py")
        
        try:
            if not is_new_skill:
                # 核心檔案或現有技能：確保目標路徑在可演化清單中
                if file_path not in valid_files and os.path.relpath(file_path, base_dir) not in valid_files:
                    print(f"⚠️ 拒絕不存在的路徑演化請求: {file_path}")
                    return None
                
                # 預先檢查 old_code 是否存在於目標檔案中
                abs_path = file_path if os.path.isabs(file_path) else os.path.join(base_dir, file_path)
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if old_code not in content:
                    print(f"⚠️ 提案失敗: old_code 與檔案內容不符 ({file_path})")
                    return None
            else:
                # 新技能：確保 old_code 為空以代表新建檔案
                if old_code.strip() != "":
                    print(f"⚠️ 新技能提案失敗: 建立新檔案時 old_code 必須為空")
                    return None
        except Exception as e:
            print(f"⚠️ 演化校驗出錯: {e}")
            return None

        if self._has_similar_evolution(file_path, old_code, reason):
            return None

        cur = self.db.cursor()
        # 使用 UTC 時間儲存
        now_str = self._utc_now_str()
        cur.execute("""
            INSERT INTO pending_evolutions (reason, file_path, old_code, new_code, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (reason, file_path, old_code, new_code, now_str))
        self.db.commit()
        return cur.lastrowid

    def _auto_evolve(self, reason: str, file_path: str, old_code: str, new_code: str) -> dict:
        """自動執行升級（支援新檔案與核心/技能 Git 隔離）"""
        if self._has_similar_evolution(file_path, old_code, reason):
            return {"success": False, "message": "已有類似的升級"}

        try:
            is_new_file = not old_code or old_code.strip() == ""
            base_dir = os.path.dirname(os.path.abspath(__file__))
            abs_path = file_path if os.path.isabs(file_path) else os.path.join(base_dir, file_path)
            
            if not is_new_file:
                if not os.path.exists(abs_path):
                    return {"success": False, "message": f"找不到檔案: {file_path}"}
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if old_code not in content:
                    return {"success": False, "message": "找不到要替換的程式碼"}
                new_content = content.replace(old_code, new_code, 1)
            else:
                new_content = new_code

            # 確保目錄存在
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # Git 策略：僅對核心檔案進行 Commit，技能模組保持輕量化
            is_core = any(core_file in file_path for core_file in EVOLVABLE_FILES)
            if is_core:
                commit_msg = f"🧬 Auto Evolution: {reason[:50]}"
                subprocess.run(["git", "add", abs_path], check=True)
                # 使用 -m 而非 -am 避免捲入其他未追蹤檔案
                subprocess.run(["git", "commit", "-m", commit_msg], check=True)
            else:
                print(f"📦 Skill Module Updated (No Git): {file_path}")

            # 記錄到資料庫
            cur = self.db.cursor()
            now_str = self._utc_now_str()
            cur.execute("""
                INSERT INTO pending_evolutions (reason, file_path, old_code, new_code, status, created_at, reviewed_at, reviewed_by)
                VALUES (?, ?, ?, ?, 'approved', ?, ?, 'AUTO')
            """, (reason, file_path, old_code, new_code, now_str, now_str))
            self.db.commit()

            # 執行自我重啟以套用變更，確保資料庫記錄已完成
            self._restart_service()

            return {"success": True, "message": f"自動升級完成: {reason[:50]}，系統正在重啟..."}
        except Exception as e:
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
                SET status = 'approved', reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
            """, (self._utc_now_str(), user_id, evolution_id))
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
            SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
        """, (self._utc_now_str(), user_id, evolution_id))
        self.db.commit()

        return {"success": True, "message": f"升級 #{evolution_id} 已拒絕"}
