import shutil
import time
import asyncio
import re
from pathlib import Path
from urllib.parse import quote

from astrbot.core.star import Star
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.message_components import Record, Reply, Plain


class VoiceDownloader(Star):
    """
    语音下载与发送插件
    用法：
    1. 引用语音发送：/下载音频 <名称>  (例如: /下载音频 exe)
    2. 发送已保存语音：/发送音频 <名称> (例如: /发送音频 exe)
    """

    def _get_save_dir(self) -> Path:
        """懒加载获取保存目录"""
        if not hasattr(self, '_save_dir') or self._save_dir is None:
            plugin_dir = Path(__file__).parent.resolve()
            self._save_dir = plugin_dir / "data" / "records"
            self._save_dir.mkdir(parents=True, exist_ok=True)
        return self._save_dir

    def _extract_name(self, event: AstrMessageEvent, cmd: str) -> str:
        """从消息文本中提取命令后的参数名称"""
        # 匹配命令后面的所有非空字符
        pattern = rf'{cmd}\s+(.+)'
        match = re.search(pattern, event.message_str)
        if match:
            # 清理名称，去除首尾空格和可能的非法文件名字符
            name = match.group(1).strip()
            # 简单过滤一下 Windows 下的非法文件名字符
            name = re.sub(r'[\\/*?:"<>|]', "", name)
            return name
        return None

    @filter.command("下载音频")
    async def download_voice(self, event: AstrMessageEvent):
        """命令：下载音频并命名保存（必须引用一条语音消息）"""
        
        # 1. 提取名称参数
        name = self._extract_name(event, "下载音频")
        if not name:
            await event.send(event.plain_result("❌ 请指定音频名称\n👉 用法：/下载音频 <名称>\n👉 示例：/下载音频 exe"))
            return

        # 2. 检查引用并获取 Record 组件
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

        # 3. 提取本地路径
        record_path = getattr(record_comp, 'path', None)
        if not record_path:
            await event.send(event.plain_result("❌ 无法获取语音的本地路径"))
            return

        # 4. 执行本地文件复制
        print(f"[VoiceDownloader] 🚀 准备保存为 [{name}]，源文件: {record_path}")
        save_path = await self._copy_local_file_with_retry(record_path, name)
        
        if save_path:
            await event.send(event.plain_result(f"✅ 语音已保存\n🏷️ 名称：{name}\n📁 路径：{save_path}"))
        else:
            await event.send(event.plain_result("❌ 保存本地语音失败，请查看控制台日志"))

    @filter.command("发送音频")
    async def send_voice(self, event: AstrMessageEvent):
        """命令：发送已保存的音频"""
        
        # 1. 提取名称参数
        name = self._extract_name(event, "发送音频")
        if not name:
            await event.send(event.plain_result("❌ 请指定音频名称\n👉 用法：/发送音频 <名称>\n👉 示例：/发送音频 exe"))
            return

        save_dir = self._get_save_dir()
        
        # 2. 查找文件 (遍历常见语音后缀)
        target_file = None
        for ext in ['.amr', '.silk', '.pcm', '.mp3', '.wav']:
            guess_path = save_dir / f"{name}{ext}"
            if guess_path.is_file():
                target_file = guess_path
                break
                
        # 如果上面没找到，用 glob 模糊匹配一下
        if not target_file:
            files = list(save_dir.glob(f"{name}.*"))
            if files:
                target_file = files[0]

        if not target_file:
            await event.send(event.plain_result(f"❌ 未找到名为 [{name}] 的音频\n💡 请检查名称是否正确"))
            return

        # 3. 发送语音
        try:
            # 🌟 核心修复：AstrBot 会自动截取 file:/// 后的路径并读取本地文件
            # 因此这里【绝对不能】使用 quote() 进行 URL 编码，直接使用 as_posix() 即可
            file_uri = f"file:///{target_file.as_posix()}"
            print(f"[VoiceDownloader] 📤 准备发送音频: {file_uri}")
            
            # 构造消息链并发送
            chain = MessageChain([Record(file=file_uri)])
            await event.send(chain)
            
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 发送音频失败: {e}")
            import traceback
            traceback.print_exc()
            await event.send(event.plain_result(f"❌ 发送音频失败: {str(e)}"))

    async def _copy_local_file_with_retry(self, src_path_str: str, name: str) -> str:
        """带重试和多重路径猜测的本地文件复制"""
        try:
            clean_str = src_path_str.strip().strip("'\"")
            src_path = Path(clean_str)
            
            print(f"[VoiceDownloader] 🔍 解析后的绝对路径: {src_path.absolute()}")

            # 尝试查找文件 (最多重试 3 次，每次等待 0.5 秒)
            target_file = None
            for attempt in range(3):
                if src_path.is_file():
                    target_file = src_path
                    break
                
                for ext in ['.amr', '.silk', '.pcm']:
                    guess_path = src_path.with_suffix(ext)
                    if guess_path.is_file():
                        target_file = guess_path
                        break
                
                if target_file:
                    break
                    
                print(f"[VoiceDownloader] ⏳ 文件暂不可用，等待 QQ 释放锁... (尝试 {attempt + 1}/3)")
                await asyncio.sleep(0.5)

            if not target_file:
                print(f"[VoiceDownloader] ❌ 源文件不存在: {src_path}")
                return None

            save_dir = self._get_save_dir()
            
            # 🌟 核心修改：使用用户指定的名称命名
            ext = target_file.suffix if target_file.suffix else ".amr"
            dest_path = save_dir / f"{name}{ext}"
            
            # 如果同名文件已存在，shutil.copy2 会直接覆盖
            shutil.copy2(target_file, dest_path)
            print(f"[VoiceDownloader] ✅ 成功保存为: {dest_path}")
            
            return str(dest_path)
            
        except PermissionError as e:
            print(f"[VoiceDownloader] ❌ 权限被拒绝 (文件可能被 QQ 独占): {e}")
            return None
        except Exception as e:
            print(f"[VoiceDownloader] ❌ 本地文件复制异常: {e}")
            import traceback
            traceback.print_exc()
            return None