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
        """插件加载时创建保存目录"""
        self.save_dir = os.path.join(self.plugin_dir, "data", "records")
        os.makedirs(self.save_dir, exist_ok=True)

    @filter.command("下载音频")
    async def download_voice(self, event: AstrMessageEvent):
        """命令：下载音频（必须引用一条语音消息）"""

        # 1. 检查引用
        reply_id = None
        for comp in event.message_obj.message:
            if isinstance(comp, Reply):
                reply_id = comp.id
                break
        if not reply_id:
            await event.send(event.plain_result("⚠️ 请先引用（回复）一条语音消息，再发送“下载音频”"))
            return

        # 2. 获取被引用消息
        try:
            msg_data = await event.bot.api.call_action("get_msg", message_id=reply_id)
        except Exception as e:
            print(f"[VoiceDownloader] get_msg 失败: {e}")
            await event.send(event.plain_result("❌ 获取被引用消息失败"))
            return
            
        if not msg_data or "message" not in msg_data:
            await event.send(event.plain_result("❌ 无法获取被引用的消息，可能已过期"))
            return

        # 3. 寻找语音段 (优先取 url，其次取 file)
        record_url = None
        record_file = None
        
        for seg in msg_data["message"]:
            if seg.get("type") == "record":
                data = seg.get("data", {})
                record_url = data.get("url")
                record_file = data.get("file")
                break
                
        if not record_url and not record_file:
            await event.send(event.plain_result("❌ 被引用的消息中不包含语音"))
            return

        # 4. 下载
        print(f"[VoiceDownloader] 提取到 url: {record_url}, file: {record_file}")
        save_path = await self._save_voice(event, record_url, record_file)
        
        if save_path:
            await event.send(event.plain_result(f"✅ 语音已保存到本地\n📁 路径：{save_path}"))
        else:
            await event.send(event.plain_result("❌ 下载语音失败，请查看控制台日志获取详细原因"))

    # ---------- 以下为内部方法 ----------
    async def _save_voice(self, event: AstrMessageEvent, url: str, file: str) -> str:
        try:
            # 策略 1：如果 get_msg 直接返回了 http url，直接下载 (最推荐)
            if url and url.startswith("http"):
                print("[VoiceDownloader] 策略1: 直接下载 url")
                return await self._download_from_url(url)

            # 策略 2：调用 get_record API 获取真实路径或 URL
            if file:
                print(f"[VoiceDownloader] 策略2: 调用 get_record, file={file}")
                try:
                    # 尝试请求 mp3 格式 (NapCat/Lagrange 等支持)
                    result = await event.bot.api.call_action("get_record", file=file, out_format="mp3")
                except Exception:
                    # 如果不支持 out_format 参数，退回到默认请求
                    result = await event.bot.api.call_action("get_record", file=file)
                
                print(f"[VoiceDownloader] get_record 返回: {result}")
                
                if isinstance(result, dict):
                    # 从 result 中提取可能的 url 或 本地路径
                    res_url = result.get("url")
                    res_file = result.get("file")
                    
                    if res_url and res_url.startswith("http"):
                        print("[VoiceDownloader] 策略2.1: 下载 get_record 返回的 url")
                        return await self._download_from_url(res_url)
                        
                    if res_file:
                        if res_file.startswith("http"):
                            print("[VoiceDownloader] 策略2.2: 下载 get_record 返回的 file (http)")
                            return await self._download_from_url(res_file)
                        if os.path.isfile(res_file):
                            print(f"[VoiceDownloader] 策略2.3: 复制本地文件 {res_file}")
                            return self._copy_local_file(res_file)
                            
                    if "base64" in result:
                        print("[VoiceDownloader] 策略2.4: 解码 base64")
                        import base64
                        data = base64.b64decode(result["base64"])
                        save_path = self._gen_save_path(".amr")
                        async with aiofiles.open(save_path, "wb") as f:
                            await f.write(data)
                        return save_path

            # 策略 3：file 本身就是一个本地绝对路径
            if file and os.path.isfile(file):
                print(f"[VoiceDownloader] 策略3: 直接复制本地文件 {file}")
                return self._copy_local_file(file)

            print(f"[VoiceDownloader] ❌ 所有策略均失败。url: {url}, file: {file}")
            return None
            
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 下载语音异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _download_from_url(self, url: str) -> str:
        try:
            # 增加超时时间和常见的 UA，防止被服务器拒绝
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {"User-Agent": "Mozilla/5.0"}
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        # 尝试从 URL 获取后缀，否则默认 .amr
                        fname = os.path.basename(url.split("?")[0])
                        ext = os.path.splitext(fname)[-1] if "." in fname else ".amr"
                        save_path = self._gen_save_path(ext)
                        async with aiofiles.open(save_path, "wb") as f:
                            await f.write(await resp.read())
                        return save_path
                    else:
                        print(f"[VoiceDownloader] HTTP 下载失败，状态码: {resp.status} for {url}")
                        return None
        except Exception as e:
            print(f"[VoiceDownloader] HTTP 下载异常: {e}")
            return None

    def _copy_local_file(self, src_path: str) -> str:
        try:
            ext = os.path.splitext(src_path)[-1] or ".amr"
            save_path = self._gen_save_path(ext)
            shutil.copy2(src_path, save_path)
            return save_path
        except Exception as e:
            print(f"[VoiceDownloader] 本地文件复制失败: {e}")
            return None

    def _gen_save_path(self, ext: str) -> str:
        if not ext.startswith("."):
            ext = "." + ext
        timestamp = int(time.time() * 1000)
        fname = f"voice_{timestamp}{ext}"
        return os.path.join(self.save_dir, fname)