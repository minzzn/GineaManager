import discord
from discord import app_commands
import os
from dotenv import load_dotenv
import json
from datetime import datetime

# .env 파일 불러오기
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

def getenv_int(key: str):
    v = os.getenv(key)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None

def getenv_int_set(key: str):
    v = os.getenv(key)
    if not v:
        return set()
    ids = set()
    for token in v.replace(",", " ").split():
        try:
            ids.add(int(token))
        except ValueError:
            pass
    return ids

TRIGGER_CHANNEL_ID = getenv_int("TRIGGER_CHANNEL_ID")
PARTICIPATE_EMOJI_ID = getenv_int("PARTICIPATE_EMOJI_ID")
COMMAND_CHANNEL_IDS = getenv_int_set("COMMAND_CHANNEL_IDS")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True
intents.message_content = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.thread_parent_map = {}
        self.load_thread_map()

    def save_thread_map(self):
        with open("thread_map.json", "w") as f:
            json.dump({str(k): v for k, v in self.thread_parent_map.items()}, f)

    def load_thread_map(self):
        try:
            with open("thread_map.json", "r") as f:
                self.thread_parent_map = {int(k): int(v) for k, v in json.load(f).items()}
        except FileNotFoundError:
            self.thread_parent_map = {}

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        await self.tree.sync()

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if self.user and payload.user_id == self.user.id:
            return

        # 커스텀 이모지 일치
        if PARTICIPATE_EMOJI_ID is None or payload.emoji.id is None or payload.emoji.id != PARTICIPATE_EMOJI_ID:
            return

        # 채널/메시지 확보
        channel = self.get_channel(payload.channel_id) or await self.fetch_channel(payload.channel_id)
        try:
            message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        
        # # 채널/메시지 확보 직후
        # print("DBG: payload", {
        #     "guild": payload.guild_id,
        #     "channel": payload.channel_id,
        #     "message": payload.message_id,
        #     "user": payload.user_id,
        #     "emoji": payload.emoji.id,
        #     "expected": PARTICIPATE_EMOJI_ID
        # })

       # 트리거 채널 판별: 메시지 채널 또는 부모 채널이 TRIGGER_CHANNEL_ID 여야 함
        msg_ch = message.channel
        parent = getattr(msg_ch, "parent", None)

        # print("DBG: trigger vars", {
        #     "msg_channel_id": msg_ch.id,
        #     "msg_channel_name": getattr(msg_ch, "name", None),
        #     "msg_channel_type": getattr(msg_ch, "type", None),  # discord.ChannelType
        #     "parent_id": getattr(msg_ch, "parent_id", None),
        #     "parent_name": getattr(parent, "name", None) if parent else None,
        #     "parent_type": getattr(parent, "type", None) if parent else None,
        #     "category_id": getattr(msg_ch, "category_id", None),
        #     "trigger_id": TRIGGER_CHANNEL_ID,
        # })

        allowed = True if TRIGGER_CHANNEL_ID is None else (
            msg_ch.id == TRIGGER_CHANNEL_ID or getattr(msg_ch, "parent_id", None) == TRIGGER_CHANNEL_ID
        )
        print("DBG: allowed_by_trigger =", allowed)

        if not allowed:
            print("STOP: not target channel")
            return

        # 채널/부모채널 판별 직후
        print("DBG: passed trigger check")
        # 이미 스레드가 붙어있으면 중복 방지
        if getattr(message, "thread", None) is not None:
            return

        # 생성 베이스 채널(텍스트 채널)
        base = message.channel.parent if getattr(message.channel, "parent", None) else message.channel

        # on_raw_reaction_add 내부, create_thread 직전에 추가/수정

        # 1) 멤버/유저 정보 안전 해석
        member = getattr(payload, "member", None)
        guild = self.get_guild(payload.guild_id) if payload.guild_id else None
        if not member and guild:
            try:
                member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                member = None
        # 유저 객체(최소한의 폴백)
        user = self.get_user(payload.user_id) or await self.fetch_user(payload.user_id)

        # 2) 표시명/멘션 만들기
        display = None
        if member and getattr(member, "display_name", None):
            display = member.display_name
        elif getattr(user, "global_name", None):
            display = user.global_name
        elif getattr(user, "name", None):
            display = user.name
        else:
            display = f"user-{payload.user_id}"

        mention = member.mention if member else f"<@{payload.user_id}>"

        # 3) 스레드 이름 안전 처리(길이/개행)
        thread_name = f"{display}님의 파티 모집 스레드 🎮"
        thread_name = thread_name.replace("\n", " ").strip()
        if len(thread_name) > 90:  # 안전 여유치(Discord 제한 고려)
            thread_name = thread_name[:90]

        # 4) 스레드 생성
        try:
            thread = await base.create_thread(
                name=thread_name,
                auto_archive_duration=60,
                message=message
            )
        except discord.Forbidden as e:
            print("ERR: Forbidden (권한 부족)", repr(e))
            return
        except discord.HTTPException as e:
            print("ERR: HTTPException", e.status, e.code, getattr(e, "text", ""))
            return

        # 5) 매핑 저장 및 안내(여기서 실제 멘션으로 알림)
        self.thread_parent_map[thread.id] = message.id
        self.save_thread_map()

        await thread.send(f"{mention}님이 파티 모집 스레드를 시작했습니다!")
        await base.send(f"{display}님의 파티 모집 스레드가 생성되었습니다: {thread.jump_url}")

client = MyClient()

@client.tree.command(name="참여자", description="현재 스레드의 :ME:참여자 리스트를 보여줍니다")
async def show_participants(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("이 명령은 스레드 내에서만 사용 가능합니다.", ephemeral=True)
        return
    thread_id = interaction.channel.id
    parent_message_id = client.thread_parent_map.get(thread_id)
    if parent_message_id is None:
        await interaction.response.send_message("님아. 혹시 기존 메세지를 삭제하셨나요? 스레드가 올바르게 생성됐는지 확인하세요.", ephemeral=True)
        return
    parent_channel = interaction.channel.parent
    try:
        orig_msg = await parent_channel.fetch_message(parent_message_id)
    except Exception:
        await interaction.response.send_message("참여자 리스트를 불러올 수 없습니다.", ephemeral=True)
        return
    for react in orig_msg.reactions:
        if getattr(react.emoji, 'id', None) == PARTICIPATE_EMOJI_ID:
            users = [u async for u in react.users() if not u.bot]
            mentions = " ".join([u.mention for u in users])
            await interaction.channel.send(
                f"**현재 참여 인원:** {mentions if mentions else '없음'}"
            )
            return
    await interaction.channel.send("아직 참여자가 없습니다.")

# 날짜 파서: 여러 포맷 지원 + ISO 대응
def parse_date(s: str):
    if not s:
        return datetime.min
    for fmt in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%Y.%m.%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(s)  # 예: 2025-08-10T12:34:56
    except Exception:
        return datetime.min  # 파싱 실패 시 가장 오래된 날짜 취급
    
@client.tree.command(name="업데이트", description="최신 봇 패치노트/새 기능 안내")
async def update_notice(interaction: discord.Interaction):
    try:
        with open("update_log.json", "r", encoding="utf-8") as f:
            logs = json.load(f)
    except Exception:
        await interaction.response.send_message("업데이트 내역 파일을 찾을 수 없습니다.")
        return
    
    if not isinstance(logs, list):
        await interaction.response.send_message("업데이트 내역 형식이 올바르지 않습니다.", ephemeral=True)
        return
    
    # 최신순(내림차순) 정렬
    logs_sorted = sorted(
        logs,
        key=lambda x: parse_date(str(x.get("date", ""))),
        reverse=True
    )

    embed = discord.Embed(
        title="📝 기니매니저 패치노트",
        description="봇의 최근 변경사항 및 새 기능을 확인하세요.",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url="https://kimberlyproject.wordpress.com/wp-content/uploads/2012/11/cropped-223917_246503182034861_7552313_n.jpg")
    for item in logs_sorted[:3]:  # 최근 3개 항목만 표시
        embed.add_field(name=f"📅 {item['date']}", value=item['desc'], inline=False)
    embed.set_footer(text="최신 기능/버그 신고는 문의 또는 DM")
    await interaction.response.send_message(embed=embed)

client.run(TOKEN)