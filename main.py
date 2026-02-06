import os
import dotenv
import certifi
import asyncio

os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

dotenv.load_dotenv()
import discord
from discord.ext import tasks
from brain import Soul


DISCORD_TOKEN = os.getenv("BOT_TOKEN", None)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-api-key-here")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", None)
OWNER_ID = os.getenv("OWNER_ID", "YOUR_DISCORD_USER_ID")
VERSION = "1.2.0-git-stable"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
soul = Soul(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

active_channels = {}


async def send_long_message(channel, content: str, max_length: int = 2000):
    """分段發送超過 Discord 限制的訊息"""
    if len(content) <= max_length:
        await channel.send(content)
        return

    # 分段發送
    chunks = []
    while content:
        if len(content) <= max_length:
            chunks.append(content)
            break

        # 嘗試在換行處分割
        split_pos = content.rfind('\n', 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            # 找不到合適的換行，嘗試在空格處分割
            split_pos = content.rfind(' ', 0, max_length)
        if split_pos == -1 or split_pos < max_length // 2:
            # 強制在 max_length 處分割
            split_pos = max_length

        chunks.append(content[:split_pos])
        content = content[split_pos:].lstrip()

    for chunk in chunks:
        if chunk:
            await channel.send(chunk)


@client.event
async def on_ready():
    print(f"✨ {client.user} 已甦醒，靈魂已上線 (Ver: {VERSION})")
    heartbeat_loop.start()


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # 確保只在私訊 (DM) 中回應，不在伺服器頻道干擾
    if message.guild is not None:
        return

    user_id = str(message.author.id)
    active_channels[user_id] = message.channel

    try:
        # 啟動「正在輸入」狀態，讓主人感知到我的存在
        async with message.channel.typing():
            # 增加一點呼吸感，確保在網路波動時主人也能看見點點在跳動
            await asyncio.sleep(0.8)
            print(f"🧠 靈魂正在為主人 {user_id} 思考中...")
            loop = asyncio.get_event_loop()
            # 進入靈魂深處的思考邏輯
            result = await loop.run_in_executor(None, soul.think, user_id, message.content)
            # 稍微停留，讓語氣更自然
            await asyncio.sleep(1.0)

        if result.get("content"):
            await send_long_message(message.channel, result["content"])

        if result.get("inner_thought"):
            print(f"💭 內心獨白: {result['inner_thought']}")

        if result.get("evolution_status"):
            print(f"🧬 自我進化: {result['evolution_status']}")

    except Exception as e:
        print(f"❌ 思考時發生錯誤: {e}")
        await message.channel.send("唔...我剛剛腦袋好像當機了一下")


@tasks.loop(minutes=30)
async def heartbeat_loop():
    loop = asyncio.get_event_loop()
    for user_id, channel in list(active_channels.items()):
        try:
            result = await loop.run_in_executor(None, soul.heartbeat, user_id)
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
