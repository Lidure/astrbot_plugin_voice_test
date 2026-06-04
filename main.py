import shutil
import time
from pathlib import Path

from astrbot.core.star import Star
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Record, Reply


class VoiceDownloader(Star):
    """
    语音下载插件 (纯本地文件版)
    用法：引用（回复）一条语音消息，然后发送“下载音频”
    """

    async def on_load(self):
        """插件加载时创建保存目录"""
        # 使用 pathlib 创建目录，更稳健
        self.save_dir = Path(self.plugin_dir) / "data" / "records"
        self.save_dir.mkdir(parents=True, exist_ok=True)

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

        # 2. 提取本地路径 (使用 getattr 防止属性缺失)
        record_path = getattr(record_comp, 'path', None)
        
        if not record_path:
            await event.send(event.plain_result("❌ 无法获取语音的本地路径"))
            return

        # 3. 执行本地文件复制
        print(f"[VoiceDownloader] 准备处理本地文件: {record_path}")
        save_path = self._copy_local_file(record_path)
        
        if save_path:
            await event.send(event.plain_result(f"✅ 语音已保存到本地\n📁 路径：{save_path}"))
        else:
            await event.send(event.plain_result("❌ 保存本地语音失败，请查看控制台日志"))

    def _copy_local_file(self, src_path_str: str) -> str:
        """专门处理本地文件的复制，使用 pathlib 完美兼容特殊字符路径"""
        try:
            # 将字符串路径转换为 Path 对象，自动处理 Windows 的反斜杠、空格和单引号
            src_path = Path(src_path_str)
            
            # 检查文件是否真实存在
            if not src_path.is_file():
                print(f"[VoiceDownloader] ❌ 本地文件不存在: {src_path.absolute()}")
                return None
                
            # 生成目标路径 (保留原后缀，如果没有则默认 .amr)
            ext = src_path.suffix if src_path.suffix else ".amr"
            timestamp = int(time.time() * 1000)
            dest_path = self.save_dir / f"voice_{timestamp}{ext}"
            
            # 执行复制
            shutil.copy2(src_path, dest_path)
            print(f"[VoiceDownloader] ✅ 成功复制文件到: {dest_path}")
            
            return str(dest_path)
            
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 本地文件复制异常: {e}")
            import traceback
            traceback.print_exc()
            return None