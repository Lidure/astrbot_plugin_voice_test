import os
import aiohttp
import aiofiles
import shutil
import time

from astrbot.core.star import Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Record, Reply


class VoiceDownloader(Star):
    """
    语音下载插件
    用法：引用（回复）一条语音消息，然后发送“下载音频”
    """

    async def on_load(self):
        self.save_dir = os.path.join(self.plugin_dir, "data", "records")
        os.makedirs(self.save_dir, exist_ok=True)

    @filter.command("下载音频")
    async def download_voice(self, event: AstrMessageEvent):
        # 1. 检查引用
        reply_id = None
        for comp in event.message_obj.message:
            if isinstance(comp, Reply):
                reply_id = comp.id
                break
        if not reply_id:
            await event.send("⚠️ 请先引用（回复）一条语音消息，再发送“下载音频”")
            return

        # 2. 获取被引用消息
        msg_data = await event.bot.api.call_action("get_msg", message_id=reply_id)
        if not msg_data or "message" not in msg_data:
            await event.send("❌ 无法获取被引用的消息，可能已过期")
            return

        # 3. 寻找语音段
        record_file = None
        for seg in msg_data["message"]:
            if seg.get("type") == "record":
                record_file = seg["data"].get("file") or seg["data"].get("url")
                break
        if not record_file:
            await event.send("❌ 被引用的消息中不包含语音")
            return

        # 4. 下载
        save_path = await self._save_voice(event, record_file)
        if save_path:
            await event.send(f"✅ 语音已保存到本地\n📁 路径：{save_path}")
        else:
            await event.send("❌ 下载语音失败，请稍后重试")

    async def _save_voice(self, event: AstrMessageEvent, file: str) -> str:
        try:
            if file.startswith("http"):
                return await self._download_from_url(file)

            result = await event.bot.api.call_action("get_record", file=file)
            if isinstance(result, dict):
                file_url = result.get("file")
                if file_url and file_url.startswith("http"):
                    return await self._download_from_url(file_url)
                if file_url and os.path.isfile(file_url):
                    return self._copy_local_file(file_url)
                if "base64" in result:
                    import base64
                    data = base64.b64decode(result["base64"])
                    save_path = self._gen_save_path(".amr")
                    async with aiofiles.open(save_path, "wb") as f:
                        await f.write(data)
                    return save_path

            if os.path.isfile(file):
                return self._copy_local_file(file)

            print(f"[VoiceDownloader] 无法识别的文件来源: {file}")
            return None
        except Exception as e:
            print(f"[VoiceDownloader] 下载语音异常: {e}")
            return None

    async def _download_from_url(self, url: str) -> str:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        fname = os.path.basename(url.split("?")[0]) or "voice.amr"
                        save_path = self._gen_save_path(os.path.splitext(fname)[-1])
                        async with aiofiles.open(save_path, "wb") as f:
                            await f.write(await resp.read())
                        return save_path
                    else:
                        print(f"[VoiceDownloader] HTTP {resp.status} for {url}")
                        return None
        except Exception as e:
            print(f"[VoiceDownloader] HTTP 下载失败: {e}")
            return None

    def _copy_local_file(self, src_path: str) -> str:
        try:
            ext = os.path.splitext(src_path)[-1]
            save_path = self._gen_save_path(ext)
            shutil.copy2(src_path, save_path)
            return save_path
        except Exception as e:
            print(f"[VoiceDownloader] 本地文件复制失败: {e}")
            return None

    def _gen_save_path(self, ext: str) -> str:
        timestamp = int(time.time() * 1000)
        fname = f"voice_{timestamp}{ext}"
        return os.path.join(self.save_dir, fname)