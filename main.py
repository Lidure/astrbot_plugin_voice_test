import shutil
import time
import asyncio
from pathlib import Path

from astrbot.core.star import Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Record, Reply


class VoiceDownloader(Star):
    """
    语音下载插件 (纯本地文件终极版)
    用法：引用（回复）一条语音消息，然后发送“下载音频”
    """

    def _get_save_dir(self) -> Path:
        """
        懒加载获取保存目录。
        不再依赖 on_load，确保在任何时候调用都能拿到正确的目录。
        """
        if not hasattr(self, '_save_dir') or self._save_dir is None:
            # 使用 __file__ 获取当前 main.py 所在的绝对路径，最稳妥
            plugin_dir = Path(__file__).parent.resolve()
            self._save_dir = plugin_dir / "data" / "records"
            self._save_dir.mkdir(parents=True, exist_ok=True)
            print(f"[VoiceDownloader] 📁 初始化保存目录: {self._save_dir}")
        return self._save_dir

    @filter.command("下载音频")
    async def download_voice(self, event: AstrMessageEvent):
        """命令：下载音频（必须引用一条语音消息）"""

        # 1. 检查引用并获取 Record 组件
        record_comp = None
        for comp in event.message_obj.message:
            if isinstance(comp, Reply):
                if hasattr(comp, 'chain') and comp.chain:
                    for sub_comp in comp.chain:
                        if type(sub_comp).__name__ == 'Record' or isinstance(sub_comp, Record):
                            record_comp = sub_comp
                            break
                break
                
        if not record_comp:
            await event.send(event.plain_result("❌ 被引用的消息中不包含语音"))
            return

        # 2. 提取本地路径
        record_path = getattr(record_comp, 'path', None)
        
        if not record_path:
            await event.send(event.plain_result("❌ 无法获取语音的本地路径"))
            return

        # 3. 执行本地文件复制（带重试机制）
        print(f"[VoiceDownloader] 🚀 开始处理本地文件: {record_path}")
        save_path = await self._copy_local_file_with_retry(record_path)
        
        if save_path:
            await event.send(event.plain_result(f"✅ 语音已保存到本地\n📁 路径：{save_path}"))
        else:
            await event.send(event.plain_result("❌ 保存本地语音失败，请查看控制台 [VoiceDownloader] 详细日志"))

    async def _copy_local_file_with_retry(self, src_path_str: str) -> str:
        """带重试和多重路径猜测的本地文件复制"""
        try:
            # 规范化路径字符串
            clean_str = src_path_str.strip().strip("'\"")
            src_path = Path(clean_str)
            
            print(f"[VoiceDownloader] 🔍 解析后的绝对路径: {src_path.absolute()}")

            # 尝试查找文件 (最多重试 3 次，每次等待 0.5 秒，防止 QQ 进程占用)
            target_file = None
            for attempt in range(3):
                if src_path.is_file():
                    target_file = src_path
                    break
                
                # 兜底猜测：如果原文件不存在，尝试加上 .amr 或 .silk 后缀
                for ext in ['.amr', '.silk', '.pcm']:
                    guess_path = src_path.with_suffix(ext)
                    if guess_path.is_file():
                        print(f"[VoiceDownloader] 💡 猜测找到文件: {guess_path}")
                        target_file = guess_path
                        break
                
                if target_file:
                    break
                    
                print(f"[VoiceDownloader] ⏳ 文件暂不可用，等待 QQ 释放锁... (尝试 {attempt + 1}/3)")
                await asyncio.sleep(0.5)

            if not target_file:
                parent_dir = src_path.parent
                if parent_dir.exists():
                    files_in_dir = [f.name for f in parent_dir.iterdir() if f.is_file()]
                    print(f"[VoiceDownloader] ❌ 文件不存在！父目录下的文件有: {files_in_dir[:10]}...")
                else:
                    print(f"[VoiceDownloader] ❌ 连父目录都不存在: {parent_dir}")
                return None

            # 🌟 核心修复：使用懒加载获取保存目录，彻底解决 save_dir 丢失问题
            save_dir = self._get_save_dir()

            # 执行复制
            ext = target_file.suffix if target_file.suffix else ".amr"
            timestamp = int(time.time() * 1000)
            dest_path = save_dir / f"voice_{timestamp}{ext}"
            
            shutil.copy2(target_file, dest_path)
            print(f"[VoiceDownloader] ✅ 成功复制文件到: {dest_path}")
            
            return str(dest_path)
            
        except PermissionError as e:
            print(f"[VoiceDownloader] ❌ 权限被拒绝 (文件可能被 QQ 独占): {e}")
            return None
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 本地文件复制异常: {e}")
            import traceback
            traceback.print_exc()
            return None