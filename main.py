# [main.py/Soveranima]
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

import os
import dotenv
import certifi
import asyncio
import base64

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

dotenv.load_dotenv()
import discord
from discord import app_commands, ui
from discord.ext import tasks
from brain import Soul

DISCORD_TOKEN = os.getenv("BOT_TOKEN", None)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", None)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", None)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gemini-2.0-flash")
OWNER_ID = os.getenv("OWNER_ID", None)
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", None)
VERSION = "2.3.2-stable"

if not DISCORD_TOKEN:
    raise ValueError("請在 .env 中設定 BOT_TOKEN")
if not OPENAI_API_KEY:
    raise ValueError("請在 .env 中設定 OPENAI_API_KEY")

intents = discord.Intents.default()
intents.message_content = True


class SoulBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.soul = Soul(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            owner_id=OWNER_ID,
            model=OPENAI_MODEL,
            tavily_api_key=TAVILY_API_KEY
        )
        self.active_channels = {}

    async def setup_hook(self):
        # 同步 Slash Commands 到 Discord
        await self.tree.sync()
        print("✅ Slash Commands 已同步")


client = SoulBot()


# ==================== 設定選單 UI ====================

class ConfigView(ui.View):
    """設定選單主視圖"""
    def __init__(self, user_id: str):
        super().__init__(timeout=120)
        self.user_id = user_id

    @ui.button(label="溫度設定", style=discord.ButtonStyle.primary, emoji="🌡️")
    async def temperature_button(self, interaction: discord.Interaction, button: ui.Button):
        settings = client.soul.get_user_settings(self.user_id)
        await interaction.response.send_message(
            f"目前溫度：`{settings['temperature']}`\n選擇新回應溫度（數值越高越有創意）：",
            view=TemperatureSelectView(self.user_id),
            ephemeral=True
        )

    @ui.button(label="心跳設定", style=discord.ButtonStyle.primary, emoji="💓")
    async def heartbeat_button(self, interaction: discord.Interaction, button: ui.Button):
        settings = client.soul.get_user_settings(self.user_id)
        heartbeat_status = "開啟" if settings["heartbeat_enabled"] else "關閉"
        await interaction.response.send_message(
            f"目前心跳：`{heartbeat_status}` (間隔：`{settings['heartbeat_interval']}` 分鐘)\n請選擇設定：",
            view=HeartbeatConfigView(self.user_id),
            ephemeral=True
        )

    @ui.button(label="時區設定", style=discord.ButtonStyle.primary, emoji="🌐")
    async def timezone_button(self, interaction: discord.Interaction, button: ui.Button):
        settings = client.soul.get_user_settings(self.user_id)
        tz_str = f"UTC{'+' if settings['timezone_offset'] >= 0 else ''}{settings['timezone_offset']}"
        await interaction.response.send_message(
            f"目前時區：`{tz_str}`\n選擇你的新時區偏移 (UTC)：",
            view=TimezoneSelectView(self.user_id),
            ephemeral=True
        )

    @ui.button(label="升級審核", style=discord.ButtonStyle.primary, emoji="🧬")
    async def evolution_button(self, interaction: discord.Interaction, button: ui.Button):
        user_id = str(interaction.user.id)
        if not client.soul.is_owner(user_id):
            await interaction.response.send_message("❌ 只有 OWNER 可以調整此設定", ephemeral=True)
            return

        status = "需要手動批准" if client.soul.is_approval_required() else "自動執行"
        await interaction.response.send_message(
            f"**升級審核設定**\n目前狀態：`{status}`",
            view=EvolutionConfigView(),
            ephemeral=True
        )

    @ui.button(label="查看目前設定", style=discord.ButtonStyle.secondary, emoji="📋")
    async def view_settings_button(self, interaction: discord.Interaction, button: ui.Button):
        settings = client.soul.get_user_settings(self.user_id)
        heartbeat_status = "開啟" if settings["heartbeat_enabled"] else "關閉"
        approval_status = "需要手動批准" if client.soul.is_approval_required() else "自動執行"
        tz_str = f"UTC{'+' if settings['timezone_offset'] >= 0 else ''}{settings['timezone_offset']}"
        dnd_str = f"{settings.get('dnd_start', 22)}:00 - {settings.get('dnd_end', 7)}:00"
        await interaction.response.send_message(
            f"**目前設定：**\n"
            f"🌡️ 溫度：`{settings['temperature']}`\n"
            f"🌐 時區：`{tz_str}`\n"
            f"💓 心跳：`{heartbeat_status}` ({settings['heartbeat_interval']} 分鐘)\n"
            f"🌙 DND 時段：`{dnd_str}`\n"
            f"🧬 升級審核：`{approval_status}`",
            ephemeral=True
        )


class TemperatureSelectView(ui.View):
    """溫度選擇視圖"""
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.select(
        placeholder="選擇溫度...",
        options=[
            discord.SelectOption(label="0.3 - 精確", value="0.3", description="回應較為一致和精確"),
            discord.SelectOption(label="0.5 - 平衡", value="0.5", description="平衡創意與一致性"),
            discord.SelectOption(label="0.8 - 創意（預設）", value="0.8", description="較有創意的回應"),
            discord.SelectOption(label="1.0 - 非常創意", value="1.0", description="最大創意，可能較不穩定"),
        ]
    )
    async def temperature_select(self, interaction: discord.Interaction, select: ui.Select):
        temp = float(select.values[0])
        client.soul.update_user_setting(self.user_id, "temperature", temp)
        await interaction.response.send_message(f"✅ 溫度已更新為：`{temp}`", ephemeral=True)


class TimezoneSelectView(ui.View):
    """時區選擇視圖"""
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.select(
        placeholder="選擇時區偏移 (UTC)...",
        options=[
            discord.SelectOption(label="UTC-8 (洛杉磯)", value="-8"),
            discord.SelectOption(label="UTC+0 (倫敦/預設)", value="0"),
            discord.SelectOption(label="UTC+7 (曼谷)", value="7"),
            discord.SelectOption(label="UTC+8 (台北/北京)", value="8"),
            discord.SelectOption(label="UTC+9 (東京/首爾)", value="9"),
        ]
    )
    async def timezone_select(self, interaction: discord.Interaction, select: ui.Select):
        offset = int(select.values[0])
        client.soul.update_user_setting(self.user_id, "timezone_offset", offset)
        await interaction.response.send_message(f"✅ 時區已更新為：`UTC{'+' if offset >= 0 else ''}{offset}`", ephemeral=True)


class HeartbeatConfigView(ui.View):
    """心跳設定視圖"""
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.button(label="開啟心跳", style=discord.ButtonStyle.success, emoji="✅")
    async def enable_heartbeat(self, interaction: discord.Interaction, button: ui.Button):
        client.soul.update_user_setting(self.user_id, "heartbeat_enabled", 1)
        await interaction.response.send_message("✅ 心跳功能已開啟", ephemeral=True)

    @ui.button(label="關閉心跳", style=discord.ButtonStyle.danger, emoji="❌")
    async def disable_heartbeat(self, interaction: discord.Interaction, button: ui.Button):
        client.soul.update_user_setting(self.user_id, "heartbeat_enabled", 0)
        await interaction.response.send_message("✅ 心跳功能已關閉", ephemeral=True)

    @ui.select(
        placeholder="設定心跳間隔...",
        options=[
            discord.SelectOption(label="15 分鐘", value="15"),
            discord.SelectOption(label="30 分鐘（預設）", value="30"),
            discord.SelectOption(label="60 分鐘", value="60"),
            discord.SelectOption(label="120 分鐘", value="120"),
        ]
    )
    async def interval_select(self, interaction: discord.Interaction, select: ui.Select):
        interval = int(select.values[0])
        client.soul.update_user_setting(self.user_id, "heartbeat_interval", interval)
        await interaction.response.send_message(f"✅ 心跳間隔已更新為：`{interval}` 分鐘", ephemeral=True)


class EvolutionConfigView(ui.View):
    """自我演化審核設定視圖（僅 OWNER）"""
    def __init__(self):
        super().__init__(timeout=60)

    @ui.button(label="需要手動批准", style=discord.ButtonStyle.primary, emoji="🔒")
    async def enable_approval(self, interaction: discord.Interaction, button: ui.Button):
        client.soul.set_global_setting("approval_required", "1")
        await interaction.response.send_message("✅ 已設定為需要手動批准升級", ephemeral=True)

    @ui.button(label="自動執行升級", style=discord.ButtonStyle.danger, emoji="⚡")
    async def disable_approval(self, interaction: discord.Interaction, button: ui.Button):
        client.soul.set_global_setting("approval_required", "0")
        await interaction.response.send_message("⚠️ 已設定為自動執行升級（無需批准）", ephemeral=True)


class ForgetView(ui.View):
    """清除記憶選擇視圖"""
    def __init__(self, user_id: str):
        super().__init__(timeout=60)
        self.user_id = user_id

    @ui.select(
        placeholder="選擇要清除的記憶類型...",
        options=[
            discord.SelectOption(label="對話記錄", value="messages", description="清除最近的對話記錄", emoji="💬"),
            discord.SelectOption(label="生活日誌", value="journal", description="清除累積的生活觀察", emoji="📔"),
            discord.SelectOption(label="事實清單", value="facts", description="清除記住的事實資料", emoji="📋"),
            discord.SelectOption(label="全部清除", value="all", description="清除所有記憶（無法復原）", emoji="🗑️"),
        ]
    )
    async def forget_select(self, interaction: discord.Interaction, select: ui.Select):
        forget_type = select.values[0]
        result = client.soul.forget(self.user_id, forget_type)
        if result["success"]:
            await interaction.response.send_message(f"✅ {result['message']}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {result['message']}", ephemeral=True)


# ==================== 輔助函數 ====================

async def send_long_message(channel, content: str, max_length: int = 2000):
    """分段發送超過 Discord 限制的訊息，並確保 Markdown 代碼塊不崩潰"""
    if len(content) <= max_length:
        await channel.send(content)
        return

    chunks = []
    while content:
        if len(content) <= max_length:
            chunks.append(content)
            break

        # 尋找分割點，優先找換行
        split_pos = content.rfind('\n', 0, max_length - 50)
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = max_length - 50

        chunk = content[:split_pos]
        
        # 處理代碼塊閉合邏輯 (SSP 強化版)
        if chunk.count("```") % 2 != 0:
            chunk += "\n```"
            content = "```python\n" + content[split_pos:].lstrip()
        else:
            content = content[split_pos:].lstrip()

        chunks.append(chunk)

    for chunk in chunks:
        if chunk.strip():
            await channel.send(chunk)


async def send_long_response(interaction: discord.Interaction, content: str, max_length: int = 2000):
    """分段發送超過 Discord 限制的 interaction 回應"""
    if len(content) <= max_length:
        await interaction.response.send_message(content)
        return

    # 先發送第一段
    chunks = []
    temp_content = content
    while temp_content:
        if len(temp_content) <= max_length:
            chunks.append(temp_content)
            break

        split_pos = temp_content.rfind('\n', 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = temp_content.rfind(' ', 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            split_pos = max_length

        chunks.append(temp_content[:split_pos])
        temp_content = temp_content[split_pos:].lstrip()

    await interaction.response.send_message(chunks[0])
    for chunk in chunks[1:]:
        if chunk:
            await interaction.followup.send(chunk)


# ==================== Slash Commands ====================

@client.tree.command(name="help", description="顯示可用指令說明")
async def cmd_help(interaction: discord.Interaction):
    help_text = """
**可用指令：**
`/status` - 查看機器人狀態與記憶統計
`/forget` - 清除對話記憶
`/config` - 開啟設定選單
`/todo` - 查看待審核的升級請求（僅限 OWNER）
`/detail` - 查看升級請求詳情（僅限 OWNER）
`/approve` - 批准升級請求（僅限 OWNER）
`/reject` - 拒絕升級請求（僅限 OWNER）
`/help` - 顯示此說明
"""
    await interaction.response.send_message(help_text, ephemeral=True)


@client.tree.command(name="status", description="查看機器人狀態與記憶統計")
async def cmd_status(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    status = client.soul.get_status(user_id)
    settings = status["settings"]
    heartbeat_status = "開啟" if settings["heartbeat_enabled"] else "關閉"

    tz_str = f"UTC{'+' if settings['timezone_offset'] >= 0 else ''}{settings['timezone_offset']}"
    status_text = (
        f"**Soveranima 狀態 (v{VERSION})**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 對話記錄：`{status['message_count']}` 則\n"
        f"📔 日誌長度：`{status['journal_length']}` 字元\n"
        f"📋 事實數量：`{status['facts_count']}` 項\n"
        f"🕐 最後互動：`{status['last_interaction']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**目前設定**\n"
        f"🌡️ 溫度：`{settings['temperature']}`\n"
        f"🌐 時區：`{tz_str}`\n"
        f"💓 心跳：`{heartbeat_status}` ({settings['heartbeat_interval']} 分鐘)"
    )
    await interaction.response.send_message(status_text)


@client.tree.command(name="forget", description="清除對話記憶")
async def cmd_forget(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.send_message("請選擇要清除的記憶類型：", view=ForgetView(user_id), ephemeral=True)


@client.tree.command(name="config", description="開啟設定選單")
async def cmd_config(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    await interaction.response.send_message("**設定選單**\n請選擇要調整的項目：", view=ConfigView(user_id), ephemeral=True)


@client.tree.command(name="todo", description="查看待審核的升級請求（僅限 OWNER）")
async def cmd_todo(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if not client.soul.is_owner(user_id):
        await interaction.response.send_message("❌ 只有 OWNER 可以查看待辦清關", ephemeral=True)
        return

    evolutions = client.soul.get_pending_evolutions()
    pending = [e for e in evolutions if e["status"] == "pending"]
    if not pending:
        await interaction.response.send_message("📋 目前沒有待審核的升級請求")
    else:
        text = "**📋 待審核升級請求：**\n"
        for e in pending[:10]:
            reason_preview = e['reason'][:40] if e['reason'] else "無說明"
            text += f"• `#{e['id']}` {reason_preview}... ({e['file_path']})\n"
        text += "\n使用 `/approve` 或 `/reject` 來審核"
        await interaction.response.send_message(text)


@client.tree.command(name="detail", description="查看升級請求詳情（僅限 OWNER）")
@app_commands.describe(id="升級請求的 ID")
async def cmd_detail(interaction: discord.Interaction, id: int):
    user_id = str(interaction.user.id)
    if not client.soul.is_owner(user_id):
        await interaction.response.send_message("❌ 只有 OWNER 可以查看詳情", ephemeral=True)
        return

    evo = client.soul.get_evolution_detail(id)
    if not evo:
        await interaction.response.send_message("❌ 找不到該升級請求", ephemeral=True)
        return

    # 處理程式碼中的三引號，避免破壞 Discord 的 Markdown 格式
    display_old = evo['old_code'][:500].replace("```", "''`")
    display_new = evo['new_code'][:500].replace("```", "''`")
    text = (
        f"**升級請求 #{evo['id']}**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📁 檔案：`{evo['file_path']}`\n"
        f"📝 原因：{evo['reason']}\n"
        f"📊 狀態：`{evo['status']}`\n"
        f"🕐 建立時間：`{evo['created_at']}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**舊程式碼：**\n```python\n{display_old}```\n"
        f"**新程式碼：**\n```python\n{display_new}```"
    )
    await send_long_response(interaction, text)


@client.tree.command(name="approve", description="批准升級請求（僅限 OWNER）")
@app_commands.describe(id="要批准的升級請求 ID")
async def cmd_approve(interaction: discord.Interaction, id: int):
    user_id = str(interaction.user.id)
    if not client.soul.is_owner(user_id):
        await interaction.response.send_message("❌ 只有 OWNER 可以批准升級請求", ephemeral=True)
        return

    result = client.soul.approve_evolution(id, user_id)
    emoji = "✅" if result["success"] else "❌"
    await interaction.response.send_message(f"{emoji} {result['message']}")


@client.tree.command(name="reject", description="拒絕升級請求（僅限 OWNER）")
@app_commands.describe(id="要拒絕的升級請求 ID")
async def cmd_reject(interaction: discord.Interaction, id: int):
    user_id = str(interaction.user.id)
    if not client.soul.is_owner(user_id):
        await interaction.response.send_message("❌ 只有 OWNER 可以拒絕升級請求", ephemeral=True)
        return

    result = client.soul.reject_evolution(id, user_id)
    emoji = "✅" if result["success"] else "❌"
    await interaction.response.send_message(f"{emoji} {result['message']}")


# ==================== Discord 事件 ====================

@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """全局 Slash Command 錯誤處理"""
    import aiohttp

    # 取得原始錯誤
    original = error.__cause__ if isinstance(error, app_commands.CommandInvokeError) else error

    # 網路相關的暫時性錯誤 - 靜默處理，只記錄日誌
    if isinstance(original, (aiohttp.ClientError, asyncio.TimeoutError)):
        print(f"⚠️ 網路錯誤 (/{interaction.command.name if interaction.command else 'unknown'}): {type(original).__name__}")
        return

    # 其他錯誤 - 嘗試通知使用者
    error_msg = "❌ 指令執行時發生錯誤，請稍後再試"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(error_msg, ephemeral=True)
        else:
            await interaction.response.send_message(error_msg, ephemeral=True)
    except Exception:
        pass  # 如果連回應都失敗，就放棄

    # 記錄錯誤以便除錯
    print(f"❌ 指令錯誤 (/{interaction.command.name if interaction.command else 'unknown'}): {original}")


@client.event
async def on_ready():
    print(f"✨ {client.user} 已甦醒，Soveranima 已上線 (Ver: {VERSION})")
    if OWNER_ID:
        print(f"👑 擁有者 ID: {OWNER_ID}")
    else:
        print("⚠️ 未設定 OWNER_ID，部分功能可能受限")
    
    # 恢復 active_channels (確保唯一性，優先保留最新紀錄)
    try:
        cur = client.soul.db.cursor()
        cur.execute("SELECT user_id, channel_id FROM last_interaction WHERE channel_id IS NOT NULL ORDER BY timestamp DESC")
        rows = cur.fetchall()
        seen_channels = set()
        for u_id, c_id in rows:
            if c_id in seen_channels:
                continue
            try:
                channel = await client.fetch_channel(int(c_id))
                client.active_channels[u_id] = channel
                seen_channels.add(c_id)
                print(f"🔗 已恢復與使用者 {u_id} 的頻道連線 (ID: {u_id})")
            except Exception as e:
                print(f"⚠️ 無法恢復頻道 {c_id}: {e}")
    except Exception as e:
        print(f"❌ 恢復頻道清單失敗: {e}")
        
    heartbeat_loop.start()


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # 確保只在私訊 (DM) 中回應
    if message.guild is not None:
        return

    user_id = str(message.author.id)
    client.active_channels[user_id] = message.channel
    # 持久化頻道 ID 以利重啟後恢復
    client.soul._update_last_interaction(user_id, message.channel.id)

    # 忽略 slash command（以 / 開頭的訊息由 Discord 處理）
    if message.content.startswith("/"):
        return

    try:
        async with message.channel.typing():
            await asyncio.sleep(0.8)
            print(f"🧠 靈魂正在為 {user_id} 思考中...")
            
            # 視覺感知邏輯：掃描當前訊息、回覆訊息及近期歷史，附帶來源標註防止幻覺
            image_url = None
            vision_context = ""

            def extract_img(msg):
                """從 Discord 訊息中提取圖片 URL（支援附件、Embed 圖片/縮圖、Sticker）"""
                if not msg: return None
                img_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff')
                # 1. 檢查附件（優先使用 proxy_url，避免 CDN token 過期導致 LLM 無法存取）
                if msg.attachments:
                    for a in msg.attachments:
                        is_image = a.filename.lower().endswith(img_exts) or (a.content_type and a.content_type.startswith('image/'))
                        if is_image:
                            return a.proxy_url or a.url
                # 2. 檢查 Embed 的 image 和 thumbnail
                if msg.embeds:
                    for e in msg.embeds:
                        if e.image and e.image.proxy_url:
                            return e.image.proxy_url
                        if e.image and e.image.url:
                            return e.image.url
                        if e.thumbnail and e.thumbnail.proxy_url:
                            return e.thumbnail.proxy_url
                        if e.thumbnail and e.thumbnail.url:
                            return e.thumbnail.url
                # 3. 檢查 Sticker
                if msg.stickers:
                    for s in msg.stickers:
                        return s.url
                return None

            # 1. 優先檢查當前訊息
            image_url = extract_img(message)
            if image_url:
                vision_context = "[來源: 當前訊息附件]"

            # 2. 檢查回覆目標
            is_reply_image = False
            if not image_url and message.reference and message.reference.message_id:
                try:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    image_url = extract_img(ref_msg)
                    if image_url:
                        vision_context = "[來源: 回覆目標訊息]"
                        is_reply_image = True
                except Exception:
                    pass

            # 3. 檢查最近歷史 (僅在非回覆且當前無圖時進行，並縮短時間鎖至 30s，且僅在訊息極短或包含關鍵字時觸發)
            if not image_url and not is_reply_image:
                keywords = ['這', '那', '圖', '看', '什麼', '誰', '哪']
                is_short = len(message.content) < 10
                has_keyword = any(k in message.content for k in keywords)
                
                if is_short or has_keyword:
                    try:
                        async for m in message.channel.history(limit=3):
                            if m.id == message.id: continue
                            if (message.created_at - m.created_at).total_seconds() > 30:
                                break
                            image_url = extract_img(m)
                            if image_url:
                                vision_context = "[來源: 30秒內歷史紀錄]"
                                break
                    except Exception:
                        pass

            if image_url:
                # 下載圖片轉 base64，避免 Discord CDN URL 過期導致 LLM 無法存取
                try:
                    import aiohttp, ssl
                    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
                    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_ssl_ctx)) as session:
                        async with session.get(image_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            if resp.status == 200:
                                img_bytes = await resp.read()
                                content_type = resp.content_type or "image/png"
                                img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                                image_url = f"data:{content_type};base64,{img_b64}"
                                print(f"👁️ [視覺] 圖片已轉為 base64 ({len(img_bytes)} bytes, {content_type})")
                            else:
                                print(f"👁️ [視覺] ⚠️ 圖片下載失敗 HTTP {resp.status}，將以原始 URL 傳入")
                except Exception as e:
                    print(f"👁️ [視覺] ⚠️ 圖片下載異常: {e}，將以原始 URL 傳入")
            else:
                print(f"👁️ [視覺] 未偵測到圖片")
            
            # 處理回覆 (Reply) 文本上下文
            processed_content = message.content
            if message.reference and message.reference.message_id:
                try:
                    ref_msg = await message.channel.fetch_message(message.reference.message_id)
                    ref_author = "我" if ref_msg.author == client.user else "你"
                    processed_content = f"[回覆{ref_author}的訊息: \"{ref_msg.content[:200]}...\"]\n{processed_content}"
                except Exception:
                    pass

            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, client.soul.think, user_id, processed_content, image_url, vision_context)
            await asyncio.sleep(1.0)

        # 如果有待執行的技能，先發送中間訊息（「讓我查一下」等），再繼續思考
        if result.get('_pending_skill'):
            if result.get("content"):
                await send_long_message(message.channel, result["content"])
            if result.get("inner_thought"):
                print(f"💭 內心獨白: {result['inner_thought']}")

            # 繼續執行技能 + 後續思考（帶 typing 指示器）
            async with message.channel.typing():
                result = await loop.run_in_executor(None, client.soul.continue_skill, result)

        if result.get("content"):
            await send_long_message(message.channel, result["content"])

        if result.get("inner_thought"):
            print(f"💭 內心獨白: {result['inner_thought']}")

    except Exception as e:
        print(f"❌ 思考時發生錯誤: {e}")
        await message.channel.send("唔...我剛剛腦袋好像當機了一下")


@tasks.loop(minutes=5)
async def heartbeat_loop():
    """心跳檢測迴圈（每 5 分鐘檢查一次，實際發送由使用者設定決定）"""
    loop = asyncio.get_event_loop()
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    
    for user_id, channel in list(client.active_channels.items()):
        try:
            # 清理超過 7 天未互動的非活動頻道 (直接從 DB 讀取 UTC 時間進行比較)
            cur = client.soul.db.cursor()
            cur.execute("SELECT timestamp FROM last_interaction WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            if row and row[0]:
                last_utc = datetime.fromisoformat(row[0])
                if last_utc.tzinfo is None:
                    last_utc = last_utc.replace(tzinfo=timezone.utc)
                
                if (now - last_utc).days > 7:
                    del client.active_channels[user_id]
                    continue

            result = await loop.run_in_executor(None, client.soul.heartbeat, user_id)
            if result and result.get("content"):
                await send_long_message(channel, result["content"])
                print(f"💓 主動關心 {user_id}: {result['content'][:50]}...")
        except Exception as e:
            print(f"❌ 心跳錯誤: {e}")


@heartbeat_loop.before_loop
async def before_heartbeat():
    await client.wait_until_ready()


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
