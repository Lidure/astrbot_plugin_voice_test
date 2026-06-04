import os
import aiohttp
import aiofiles
import shutil
import time
from urllib.parse import quote
from pathlib import Path

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

        # 1. 检查引用并获取 Record 组件
        record_comp = None
        for comp in event.message_obj.message:
            if isinstance(comp, Reply):
                if hasattr(comp, 'chain') and comp.chain:
                    for sub_comp in comp.chain:
                        # 兼容类名判断和类型枚举判断
                        if type(sub_comp).__name__ == 'Record' or isinstance(sub_comp, Record):
                            record_comp = sub_comp
                            break
                break
                
        if not record_comp:
            await event.send(event.plain_result("❌ 被引用的消息中不包含语音，或无法解析引用消息"))
            return

        # 2. 提取属性 (使用 getattr 防止某些平台缺少属性)
        record_url = getattr(record_comp, 'url', None)
        record_path = getattr(record_comp, 'path', None)
        record_file = getattr(record_comp, 'file', None)
        
        print(f"[VoiceDownloader] 提取到: path={record_path}, url={record_url}, file={record_file}")

        # 3. 执行保存
        save_path = await self._save_voice(event, record_url, record_path, record_file)
        
        if save_path:
            await event.send(event.plain_result(f"✅ 语音已保存到本地\n📁 路径：{save_path}"))
        else:
            await event.send(event.plain_result("❌ 下载语音失败，请查看控制台 [VoiceDownloader] 日志"))

    async def _save_voice(self, event: AstrMessageEvent, url: str, path: str, file_id: str) -> str:
        try:
            # 🌟 核心策略 1：利用 file:// 协议让 OneBot 框架底层直接读取本地文件
            # 这能完美绕过腾讯 URL 防盗链和 Python 路径空格/单引号解析问题
            if path:
                try:
                    # 规范化路径并转换为 file:// URI
                    abs_path = str(Path(path).resolve())
                    # 对路径进行 URL 编码，防止空格和单引号导致 URI 解析失败
                    file_uri = "file:///" + quote(abs_path.replace("\\", "/").lstrip("/"))
                    
                    print(f"[VoiceDownloader] 策略1: 尝试通过 file:// URI 读取: {file_uri}")
                    result = await event.bot.api.call_action("get_record", file=file_uri, out_format="mp3")
                    
                    if isinstance(result, dict) and "file" in result:
                        res_file = result["file"]
                        if res_file and os.path.isfile(res_file):
                            print(f"[VoiceDownloader] 策略1成功: 获取到真实路径 {res_file}")
                            return self._copy_local_file(res_file)
                except Exception as e:
                    print(f"[VoiceDownloader] 策略1 (file://) 失败: {e}")

            # 策略 2：直接复制本地文件 (作为策略1的备用)
            if path and os.path.isfile(path):
                print(f"[VoiceDownloader] 策略2: 直接复制本地文件 {path}")
                return self._copy_local_file(path)

            # 策略 3：通过 HTTP URL 下载 (如果前两者都失败)
            if url and url.startswith("http"):
                print(f"[VoiceDownloader] 策略3: 尝试 HTTP 下载 {url}")
                return await self._download_from_url(url)

            # 策略 4：兜底调用 get_record
            if file_id:
                print(f"[VoiceDownloader] 策略4: 兜底调用 get_record, file={file_id}")
                try:
                    result = await event.bot.api.call_action("get_record", file=file_id, out_format="mp3")
                except Exception:
                    result = await event.bot.api.call_action("get_record", file=file_id)
                
                if isinstance(result, dict):
                    res_file = result.get("file")
                    if res_file and os.path.isfile(res_file):
                        return self._copy_local_file(res_file)
                    res_url = result.get("url")
                    if res_url and res_url.startswith("http"):
                        return await self._download_from_url(res_url)

            print(f"[VoiceDownloader] ❌ 所有策略均失败。")
            return None
            
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 下载语音异常: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _download_from_url(self, url: str) -> str:
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://qq.com" # 尝试伪造 Referer 绕过防盗链
            }
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        fname = os.path.basename(url.split("?")[0])
                        ext = os.path.splitext(fname)[-1] if "." in fname else ".amr"
                        save_path = self._gen_save_path(ext)
                        async with aiofiles.open(save_path, "wb") as f:
                            await f.write(await resp.read())
                        return save_path
                    else:
                        print(f"[VoiceDownloader] HTTP 下载失败，状态码: {resp.status}")
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