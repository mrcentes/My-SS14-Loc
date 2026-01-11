"""
SS14 自动化汉化工具箱 v3.2
==========================
支持 GUI 和命令行两种模式，集成提取、同步、合并功能。

优化特性:
- 一键工作流
- 目录自动检测
- 进度条
- API 请求重试
- 可配置字段列表
- 高DPI屏幕支持
- 增量提取模式
"""

import os
import sys
import json
import argparse
import subprocess
import threading
import io
import time
import hashlib
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Set
from collections import defaultdict, deque
import logging
from logging.handlers import TimedRotatingFileHandler

# ==================== 日志配置 (Logging) ====================

class GuiHandler(logging.Handler):
    """
    自定义日志处理器，将日志发送到 GUI。
    使用队列缓存日志，直到 GUI 准备好显示。
    """
    def __init__(self, max_len=5000):
        super().__init__()
        self.log_buffer = deque(maxlen=max_len)
        self.gui_callback = None

    def emit(self, record):
        try:
            msg = self.format(record)
            # 保存日志级别和消息，以便 GUI 进行颜色高亮
            self.log_buffer.append((record.levelname, msg))
            if self.gui_callback:
                self.gui_callback()
        except Exception:
            self.handleError(record)
            
    def set_callback(self, callback):
        self.gui_callback = callback
        
    def pop_logs(self):
        """获取并清除所有缓存的日志"""
        logs = list(self.log_buffer)
        self.log_buffer.clear()
        return logs

# 全局 GUI 日志处理器实例
gui_log_handler = GuiHandler()

def setup_logging():
    """初始化日志系统"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    log_file = log_dir / f"ss14_tracker_{datetime.now().strftime('%Y-%m-%d')}.log"
    
    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 清除旧的处理器（防止重复）
    if logger.handlers:
        logger.handlers.clear()
    
    # 1. 文件处理器 (自动按天切割，保留30天)
    file_handler = TimedRotatingFileHandler(
        log_file, when="midnight", interval=1, backupCount=30, encoding='utf-8'
    )
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 2. 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 3. GUI 处理器
    # GUI 日志不需要时间戳（GUI 自己会加或者已经包含了），这里为了统一格式，简单处理
    # 如果 GUI 需要根据内容高亮，我们在 emit 中已经保存了 levelname
    gui_log_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(gui_log_handler)
    
    logging.info(f"日志系统已初始化，日志文件: {log_file}")


# ==================== 高 DPI 支持 (Windows) ====================
# 在导入 tkinter 之前设置 DPI 感知，解决 2K/4K 屏幕字体模糊问题

def enable_high_dpi():
    """启用 Windows 高 DPI 支持"""
    if sys.platform == 'win32':
        try:
            from ctypes import windll
            # 设置进程级别的 DPI 感知
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # 回退到旧版 API
                windll.user32.SetProcessDPIAware()
            except Exception:
                pass

# 在加载 GUI 前调用
enable_high_dpi()

# ==================== 常量配置 (Constants) ====================

# 默认可翻译字段列表（可在配置中修改）
DEFAULT_TRANSLATABLE_FIELDS = ['name', 'description']

# API 重试配置
API_RETRY_COUNT = 3
API_RETRY_DELAY = 2  # 秒

# 配置文件名
CONFIG_FILE = "config.json"

# 提取输出目录（用于按文件夹分组模式）
EXTRACT_OUTPUT_DIR = "extracted"

# ==================== FTL 键检测 (FTL Key Detection) ====================

def is_ftl_key(text: str) -> bool:
    """
    检测字符串是否为 FTL 本地化键。
    
    FTL 键特征：
    - 不包含空格
    - 包含连字符 -
    - 格式如 "word-word-word" 或 "word-word-Word"（kebab-case 风格）
    - 至少有3段（2个连字符）
    
    正常文本特征（不应过滤）：
    - 包含空格（如 "Pride-O-Mat restock box"）
    - 只有1-2段连字符连接（如 "AK-47"）
    - 包含非字母字符（数字、特殊符号等）
    
    示例：
    - "loadout-group-weapon" -> True (FTL 键)
    - "item-component-size-Tiny" -> True (FTL 键)
    - "Pride-O-Mat restock box" -> False (包含空格，是正常文本)
    - "AK-47" -> False (只有2段，不是 FTL 键)
    - "Assault Rifle" -> False (无连字符)
    """
    if not text or not isinstance(text, str):
        return False
    
    text = text.strip()
    
    # 正常文本包含空格，直接放行
    if ' ' in text:
        return False
    
    # 必须包含连字符
    if '-' not in text:
        return False
    
    # 分割为段
    parts = text.split('-')
    
    # FTL 键通常至少有3段（如 xxx-yyy-zzz）
    # 只有2段的如 "AK-47" 或 "O-Mat" 不太可能是 FTL 键
    if len(parts) < 3:
        return False
    
    # 检查每段是否为纯字母（FTL 键每段都是单词）
    for part in parts:
        # 允许空段（如 xxx--yyy）也视为 FTL 键
        if part and not part.isalpha():
            return False
    
    return True

# ==================== 中文检测 (Chinese Detection) ====================

def contains_chinese(text: str) -> bool:
    """
    检测字符串是否包含中文字符。
    用于判断是否需要标记为已翻译状态。
    
    CJK统一汉字范围：\u4e00-\u9fff
    """
    if not text or not isinstance(text, str):
        return False
    return any('\u4e00' <= c <= '\u9fff' for c in text)

# ==================== 共享工具 (Utils) ====================

# 全局进度回调（用于 GUI 更新进度条）
_progress_callback: Optional[Callable[[int, int, str], None]] = None
# 全局停止检查回调（用于长时间操作检查是否需要停止）
_stop_check_callback: Optional[Callable[[], bool]] = None

def set_progress_callback(callback: Optional[Callable[[int, int, str], None]]):
    """设置进度回调函数 (current, total, message)"""
    global _progress_callback
    _progress_callback = callback

def set_stop_check_callback(callback: Optional[Callable[[], bool]]):
    """设置停止检查回调函数，返回 True 表示需要停止"""
    global _stop_check_callback
    _stop_check_callback = callback

def should_stop() -> bool:
    """检查是否应该停止当前操作"""
    if _stop_check_callback:
        return _stop_check_callback()
    return False

def report_progress(current: int, total: int, message: str = ""):
    """报告进度"""
    if _progress_callback:
        _progress_callback(current, total, message)

def log(message: str, level: str = "INFO"):
    """
    兼容旧代码的日志适配器，转发到 logging 模块。
    """
    lvl_name = level.upper()
    # 映射自定义级别名称到 logging 级别
    if lvl_name == "ERROR":
        lvl = logging.ERROR
    elif lvl_name == "WARNING":
        lvl = logging.WARNING
    elif lvl_name == "DEBUG":
        lvl = logging.DEBUG
    else:
        lvl = logging.INFO
    
    logging.log(lvl, message)

def error(message: str):
    """输出错误并退出"""
    log(message, "ERROR")
    sys.exit(1)

def detect_game_directory() -> Optional[str]:
    """
    自动检测游戏目录。
    检查常见的 SS14 目录结构。
    """
    candidates = [
        "Resources/Prototypes",
        "Content/Resources/Prototypes",
        "Resources",
        "Content",
    ]
    
    for candidate in candidates:
        if os.path.isdir(candidate):
            log(f"自动检测到游戏目录: {candidate}")
            return candidate
    
    return None

# ==================== YAML 处理器 (YAML Processor) ====================

try:
    from ruamel.yaml import YAML
    HAS_RUAMEL = True
except ImportError:
    HAS_RUAMEL = False
    import yaml

class YAMLProcessor:
    """YAML 处理器 - 使用 ruamel.yaml 保留注释、格式和自定义标签。"""
    
    def __init__(self):
        if HAS_RUAMEL:
            self._yaml = YAML()
            self._yaml.preserve_quotes = True
            self._yaml.width = 4096  # 防止自动换行
            self._yaml.default_flow_style = None  # 保留原始流式样式
            self._yaml.allow_duplicate_keys = True
            self._yaml.indent(mapping=2, sequence=4, offset=2)
        else:
            self._yaml = None
            print("警告: 未找到 ruamel.yaml。回退到基础 PyYAML（将丢失格式）。")
    
    def load(self, file_path: str) -> Any:
        """加载 YAML 文件"""
        with open(file_path, 'r', encoding='utf-8') as f:
            if HAS_RUAMEL:
                return self._yaml.load(f)
            else:
                return yaml.safe_load(f)
    
    def dump(self, data: Any, file_path: str):
        """保存 YAML 文件（保留格式）"""
        with open(file_path, 'w', encoding='utf-8') as f:
            if HAS_RUAMEL:
                self._yaml.dump(data, f)
            else:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, 
                         default_flow_style=False, indent=2)

    def load_from_string(self, content: str) -> Any:
        """从字符串加载 YAML"""
        if HAS_RUAMEL:
            return self._yaml.load(io.StringIO(content))
        else:
            return yaml.safe_load(content)

# ==================== Paratranz 客户端 (PZ Client) ====================

class PZClient:
    """
    Paratranz API 客户端
    根据官方文档实现：https://paratranz.cn/docs
    """
    BASE_URL = "https://paratranz.cn/api"

    def __init__(self, project_id: int, token: str):
        self.project_id = project_id
        self.token = token
        # 官方文档要求：Authorization: Bearer {TOKEN}
        self.headers = {"Authorization": f"Bearer {token}"}
        if not project_id or not token:
            raise ValueError("需要提供 Project ID 和 Token")
        log(f"初始化 Paratranz 客户端: 项目ID={project_id}")

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """带重试的请求"""
        # HTTP 状态码说明（参考 Paratranz API 文档）
        STATUS_CODES = {
            200: "成功",
            201: "创建成功",
            302: "重定向",
            400: "参数错误",
            401: "Token 错误或过期",
            403: "没有权限",
            404: "资源不存在",
            405: "HTTP方法错误",
            429: "请求过于频繁",
            500: "服务器错误",
            502: "服务器无响应",
            503: "服务不可用",
            504: "服务超时"
        }
        
        last_error = None
        for attempt in range(API_RETRY_COUNT):
            try:
                log(f"发送请求: {method} {url}")
                response = requests.request(method, url, headers=self.headers, timeout=30, **kwargs)
                
                # 获取状态码说明
                status_desc = STATUS_CODES.get(response.status_code, "未知状态")
                log(f"响应状态码: {response.status_code} ({status_desc})")
                
                # 处理常见错误
                if response.status_code == 401:
                    log("❌ [401] Token 错误或已过期，请检查你的 API Token", "ERROR")
                    return response
                
                if response.status_code == 403:
                    log("❌ [403] 没有权限访问该资源", "ERROR")
                    return response
                
                if response.status_code == 404:
                    log("❌ [404] 资源不存在，请检查项目ID是否正确", "ERROR")
                    return response
                
                if response.status_code == 400:
                    try:
                        error_msg = response.json().get('message', response.text[:100])
                    except:
                        error_msg = response.text[:100]
                    log(f"❌ [400] 参数错误: {error_msg}", "ERROR")
                    return response
                
                if response.status_code >= 500:
                    log(f"⚠️ [{response.status_code}] 服务器错误，可能需要稍后重试", "WARNING")
                    return response
                
                # 处理速率限制
                if response.status_code == 429:
                    wait_time = int(response.headers.get('Retry-After', API_RETRY_DELAY * 2))
                    log(f"⚠️ [429] API 速率限制，等待 {wait_time} 秒后重试...", "WARNING")
                    time.sleep(wait_time)
                    continue
                
                return response
                
            except requests.exceptions.RequestException as e:
                last_error = e
                log(f"❌ 请求异常: {e}", "ERROR")
                if attempt < API_RETRY_COUNT - 1:
                    log(f"⏳ {API_RETRY_DELAY} 秒后重试 ({attempt + 1}/{API_RETRY_COUNT})...", "WARNING")
                    time.sleep(API_RETRY_DELAY)
                    
        raise last_error if last_error else Exception("请求失败")

    def test_connection(self) -> bool:
        """测试 API 连接和 Token 有效性"""
        log("正在测试 API 连接...")
        try:
            url = f"{self.BASE_URL}/projects/{self.project_id}"
            response = self._request_with_retry("GET", url)
            
            if response.status_code == 200:
                data = response.json()
                project_name = data.get('name', '未知')
                log(f"✅ 连接成功！项目名称: {project_name}")
                return True
            elif response.status_code == 401:
                log("❌ Token 无效或已过期", "ERROR")
                return False
            elif response.status_code == 404:
                log(f"❌ 项目 ID {self.project_id} 不存在", "ERROR")
                return False
            else:
                try:
                    error_msg = response.json().get('message', response.text)
                except:
                    error_msg = response.text
                log(f"❌ 连接失败 ({response.status_code}): {error_msg}", "ERROR")
                return False
        except Exception as e:
            log(f"❌ 连接测试失败: {e}", "ERROR")
            return False

    def get_file_id(self, filename: str, remote_path: str = "/") -> Optional[int]:
        """
        通过文件名和路径获取文件ID
        
        参数:
            filename: 文件名
            remote_path: 远程路径（用于精确匹配，避免同名文件冲突）
        """
        url = f"{self.BASE_URL}/projects/{self.project_id}/files"
        try:
            response = self._request_with_retry("GET", url)
            if response.status_code != 200:
                log(f"获取文件列表失败: {response.text}", "ERROR")
                return None
                
            files = response.json()
            log(f"项目中共有 {len(files)} 个文件")
            
            # 构建完整路径进行匹配
            # Paratranz 文件的 name 字段包含完整路径，如 "Entities/Clothing.json"
            expected_full_path = (remote_path.strip('/') + '/' + filename).lstrip('/')
            
            for f in files:
                file_name = f.get('name', '')
                # 先尝试完整路径匹配
                if file_name == expected_full_path:
                    log(f"找到文件 (完整路径): {expected_full_path} (ID: {f.get('id')})")
                    return f.get('id')
            
            # 回退：仅按文件名匹配（兼容旧版本）
            for f in files:
                file_name = f.get('name', '')
                if file_name == filename or file_name.endswith('/' + filename):
                    log(f"找到文件 (文件名匹配): {file_name} (ID: {f.get('id')})")
                    return f.get('id')
            
            log(f"未找到文件: {expected_full_path}", "WARNING")
            return None
        except Exception as e:
            log(f"获取文件列表错误: {e}", "ERROR")
            return None

    def upload_file(self, file_path: str, remote_path: str = "/") -> bool:
        """上传文件到 Paratranz（创建或更新）"""
        if not os.path.exists(file_path):
            log(f"❌ 未找到本地文件: {file_path}", "ERROR")
            return False

        filename = os.path.basename(file_path)
        log(f"准备上传文件: {filename} -> {remote_path}")
        
        # 传递 remote_path 进行精确匹配
        file_id = self.get_file_id(filename, remote_path)

        try:
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, 'application/json')}
                
                if file_id:
                    log(f"更新现有文件: {filename} (ID: {file_id})")
                    url = f"{self.BASE_URL}/projects/{self.project_id}/files/{file_id}"
                    response = self._request_with_retry("POST", url, files=files)
                else:
                    log(f"创建新文件: {filename} 在 {remote_path}")
                    url = f"{self.BASE_URL}/projects/{self.project_id}/files"
                    data = {'path': remote_path}
                    response = self._request_with_retry("POST", url, files=files, data=data)

            if response.status_code in [200, 201]:
                log("✅ 上传成功")
                return True
            else:
                try:
                    error_msg = response.json().get('message', response.text)
                except:
                    error_msg = response.text
                log(f"❌ 上传失败: {error_msg}", "ERROR")
                return False
        except Exception as e:
            log(f"❌ 上传异常: {e}", "ERROR")
            return False

    def upload_folder(self, local_dir: str) -> Dict[str, int]:
        """
        批量上传目录下所有 JSON 文件到 Paratranz，保持路径结构。
        
        文件名格式约定（按优先级）：
        1. 完整路径格式：Entities/Clothing.json -> 上传到 /Entities/Clothing/ 路径
        2. 下划线格式（旧版兼容）：Entities_Clothing.json -> 上传到 /Entities/Clothing/ 路径
        
        返回统计信息。
        """
        stats = {"uploaded": 0, "failed": 0, "skipped": 0}
        
        if not os.path.isdir(local_dir):
            log(f"❌ 目录不存在: {local_dir}", "ERROR")
            return stats
        
        # 递归查找所有 JSON 文件（支持子目录结构）
        json_files = []
        for root, dirs, files in os.walk(local_dir):
            for f in files:
                if f.endswith('.json'):
                    # 保存相对路径
                    rel_path = os.path.relpath(os.path.join(root, f), local_dir)
                    json_files.append(rel_path)
        
        if not json_files:
            log(f"⚠️ 目录中没有 JSON 文件: {local_dir}", "WARNING")
            return stats
        
        log(f"📤 批量上传 {len(json_files)} 个文件到 Paratranz...")
        
        for i, rel_path in enumerate(json_files):
            # 检查是否需要停止
            if should_stop():
                log(f"⏹ 上传已停止，已完成 {stats['uploaded']} 个")
                stats["skipped"] = len(json_files) - i
                break
            
            file_path = os.path.join(local_dir, rel_path)
            try:
                file_size = os.path.getsize(file_path)
            except:
                file_size = 0
            
            # 从相对路径推断远程路径
            # 例如：Entities/Clothing.json -> /Entities/Clothing/
            # 或者：Entities/Clothing/Hats.json -> /Entities/Clothing/Hats/
            remote_dir = os.path.dirname(rel_path).replace('\\', '/')
            base_name = os.path.splitext(os.path.basename(rel_path))[0]
            
            if remote_dir:
                # 有子目录：Entities/Clothing/Hats.json -> /Entities/Clothing/Hats/
                remote_path = '/' + remote_dir + '/' + base_name + '/'
            else:
                # 根目录下：Entities.json -> /Entities/ 或 Entities/Clothing.json -> /Entities/Clothing/
                # 检查文件名是否包含路径分隔符（完整路径格式）
                if '/' in base_name:
                    remote_path = '/' + base_name + '/'
                else:
                    remote_path = '/' + base_name + '/'
            
            # 清理多余的斜杠
            remote_path = '/' + remote_path.strip('/').replace('//', '/') + '/'
            if remote_path == '//':
                remote_path = '/'
            
            log(f"[{i+1}/{len(json_files)}] 上传: {rel_path} ({file_size/1024:.1f}KB) -> {remote_path}")
            report_progress(i + 1, len(json_files), f"上传: {os.path.basename(rel_path)}")
            
            if self.upload_file(file_path, remote_path):
                stats["uploaded"] += 1
            else:
                stats["failed"] += 1
            
            # 避免 API 速率限制
            time.sleep(0.5)
        
        log(f"✅ 批量上传完成。成功: {stats['uploaded']}，失败: {stats['failed']}，跳过: {stats['skipped']}")
        return stats

    def upload_translation(self, file_path: str, remote_path: str = "/", force: bool = False) -> bool:
        """
        上传译文到 Paratranz（仅更新翻译，不改原文）。
        
        使用 API: POST /projects/{projectId}/files/{fileId}/translation
        
        参数:
            file_path: 本地 JSON 文件路径（包含 translation 字段）
            remote_path: 远程路径（用于匹配对应的原文文件）
            force: 是否强制覆盖已人工编辑的词条（默认 False）
        """
        if not os.path.exists(file_path):
            log(f"❌ 未找到本地文件: {file_path}", "ERROR")
            return False

        filename = os.path.basename(file_path)
        log(f"📝 准备上传译文: {filename} -> {remote_path}")
        
        # 查找对应的原文文件 ID
        file_id = self.get_file_id(filename, remote_path)
        if not file_id:
            log(f"❌ 未找到对应的原文文件，请先上传原文: {filename}", "ERROR")
            return False

        try:
            url = f"{self.BASE_URL}/projects/{self.project_id}/files/{file_id}/translation"
            
            with open(file_path, 'rb') as f:
                files = {'file': (filename, f, 'application/json')}
                data = {'force': 'true' if force else 'false'}
                response = self._request_with_retry("POST", url, files=files, data=data)

            if response.status_code in [200, 201]:
                log(f"✅ 译文上传成功: {filename}")
                return True
            else:
                try:
                    error_msg = response.json().get('message', response.text)
                except:
                    error_msg = response.text
                log(f"❌ 译文上传失败: {error_msg}", "ERROR")
                return False
        except Exception as e:
            log(f"❌ 译文上传异常: {e}", "ERROR")
            return False

    def upload_translation_folder(self, local_dir: str, force: bool = False) -> Dict[str, int]:
        """
        批量上传目录下所有 JSON 文件的译文到 Paratranz。
        
        参数:
            local_dir: 本地目录（包含 JSON 文件）
            force: 是否强制覆盖已人工编辑的词条
        
        返回统计信息。
        """
        stats = {"uploaded": 0, "failed": 0, "skipped": 0}
        
        if not os.path.isdir(local_dir):
            log(f"❌ 目录不存在: {local_dir}", "ERROR")
            return stats
        
        # 递归查找所有 JSON 文件
        json_files = []
        for root, dirs, files in os.walk(local_dir):
            for f in files:
                if f.endswith('.json'):
                    rel_path = os.path.relpath(os.path.join(root, f), local_dir)
                    json_files.append(rel_path)
        
        if not json_files:
            log(f"⚠️ 目录中没有 JSON 文件: {local_dir}", "WARNING")
            return stats
        
        log(f"📝 批量上传译文 {len(json_files)} 个文件到 Paratranz...")
        if force:
            log("⚠️ 强制模式已启用，将覆盖已人工编辑的词条", "WARNING")
        
        for i, rel_path in enumerate(json_files):
            if should_stop():
                log(f"⏹ 上传已停止，已完成 {stats['uploaded']} 个")
                stats["skipped"] = len(json_files) - i
                break
            
            file_path = os.path.join(local_dir, rel_path)
            
            # 推断远程路径（与 upload_folder 逻辑一致）
            remote_dir = os.path.dirname(rel_path).replace('\\', '/')
            base_name = os.path.splitext(os.path.basename(rel_path))[0]
            
            if remote_dir:
                remote_path = '/' + remote_dir + '/' + base_name + '/'
            else:
                remote_path = '/' + base_name + '/'
            
            remote_path = '/' + remote_path.strip('/').replace('//', '/') + '/'
            if remote_path == '//':
                remote_path = '/'
            
            log(f"[{i+1}/{len(json_files)}] 译文: {rel_path} -> {remote_path}")
            report_progress(i + 1, len(json_files), f"译文: {os.path.basename(rel_path)}")
            
            if self.upload_translation(file_path, remote_path, force):
                stats["uploaded"] += 1
            else:
                stats["failed"] += 1
            
            time.sleep(0.5)
        
        log(f"✅ 译文批量上传完成。成功: {stats['uploaded']}，失败: {stats['failed']}，跳过: {stats['skipped']}")
        return stats

    def trigger_export(self) -> bool:
        """触发项目导出（生成压缩包）"""
        log("触发项目导出...")
        url = f"{self.BASE_URL}/projects/{self.project_id}/artifacts"
        try:
            response = self._request_with_retry("POST", url)
            if response.status_code in [200, 201]:
                log("✅ 导出任务已触发")
                return True
            elif response.status_code == 403:
                log("⚠️ 没有触发导出的权限（仅管理员可用），将尝试下载现有导出", "WARNING")
                return True  # 继续尝试下载
            else:
                try:
                    error_msg = response.json().get('message', response.text)
                except:
                    error_msg = response.text
                log(f"触发导出失败: {error_msg}", "WARNING")
                return True  # 继续尝试下载现有导出
        except Exception as e:
            log(f"触发导出异常: {e}", "WARNING")
            return True  # 继续尝试下载

    def download_artifacts(self, save_path: str) -> bool:
        """
        下载项目导出的压缩包（包含所有翻译）
        根据官方文档：GET /projects/{projectId}/artifacts/download
        """
        log("正在下载翻译压缩包...")
        
        # 先尝试触发导出（可能需要管理员权限）
        self.trigger_export()
        
        # 等待一小会让服务器准备
        time.sleep(1)
        
        url = f"{self.BASE_URL}/projects/{self.project_id}/artifacts/download"
        
        try:
            # 使用 allow_redirects=True 跟随重定向
            log(f"请求下载: {url}")
            response = requests.get(url, headers=self.headers, timeout=60, allow_redirects=True, stream=True)
            
            log(f"下载响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                # 保存为 zip 文件
                zip_path = save_path.replace('.json', '.zip') if save_path.endswith('.json') else save_path + '.zip'
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                log(f"✅ 已下载压缩包到: {zip_path}")
                
                # 解压并提取翻译
                return self._extract_translations_from_zip(zip_path, save_path)
                
            elif response.status_code == 302:
                # 手动处理重定向
                redirect_url = response.headers.get('Location')
                if redirect_url:
                    log(f"重定向到: {redirect_url}")
                    response = requests.get(redirect_url, timeout=60, stream=True)
                    if response.status_code == 200:
                        zip_path = save_path.replace('.json', '.zip') if save_path.endswith('.json') else save_path + '.zip'
                        with open(zip_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        log(f"✅ 已下载压缩包到: {zip_path}")
                        return self._extract_translations_from_zip(zip_path, save_path)
            else:
                try:
                    error_msg = response.json().get('message', response.text[:200])
                except:
                    error_msg = response.text[:200] if response.text else "未知错误"
                log(f"❌ 下载失败 ({response.status_code}): {error_msg}", "ERROR")
                return False
                
        except Exception as e:
            log(f"❌ 下载异常: {e}", "ERROR")
            return False

    def _extract_translations_from_zip(self, zip_path: str, output_path: str) -> bool:
        """从下载的压缩包中提取翻译数据"""
        import zipfile
        
        try:
            log(f"正在解压: {zip_path}")
            
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # 列出压缩包内容
                file_list = zf.namelist()
                log(f"压缩包内包含 {len(file_list)} 个文件")
                
                # 查找 JSON 文件
                json_files = [f for f in file_list if f.endswith('.json')]
                
                if json_files:
                    # 提取第一个 JSON 文件
                    target_file = json_files[0]
                    log(f"提取文件: {target_file}")
                    
                    with zf.open(target_file) as source:
                        content = source.read()
                        with open(output_path, 'wb') as target:
                            target.write(content)
                    
                    log(f"✅ 已保存翻译到: {output_path}")
                    return True
                else:
                    # 如果没有 JSON，解压所有文件到当前目录
                    extract_dir = os.path.dirname(output_path) or '.'
                    zf.extractall(extract_dir)
                    log(f"✅ 已解压所有文件到: {extract_dir}")
                    return True
                    
        except zipfile.BadZipFile:
            log("❌ 下载的文件不是有效的压缩包", "ERROR")
            return False
        except Exception as e:
            log(f"❌ 解压失败: {e}", "ERROR")
            return False
        finally:
            # 清理临时 zip 文件
            try:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except:
                pass

    def download_file(self, save_path: str, remote_filename: str = "") -> bool:
        """
        下载翻译文件
        使用 artifacts/download 端点下载项目导出
        """
        return self.download_artifacts(save_path)

# ==================== 提取逻辑 (Extraction Logic) ====================

# 哈希缓存文件名
HASH_CACHE_FILE = ".extract_cache.json"

def compute_file_hash(file_path: str) -> str:
    """计算文件的 MD5 哈希值"""
    hasher = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def load_hash_cache(cache_file: str) -> Dict[str, str]:
    """加载哈希缓存"""
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_hash_cache(cache_file: str, cache: Dict[str, str]):
    """保存哈希缓存"""
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)

def extract_strings(scan_dir: str, output_file: str, fields: List[str] = None, 
                    incremental: bool = False, filter_ftl: bool = True) -> Dict[str, int]:
    """
    扫描 scan_dir 中的 YAML 文件并提取字符串到 output_file。
    
    参数:
        scan_dir: 扫描目录
        output_file: 输出 JSON 文件
        fields: 要提取的字段列表
        incremental: 是否使用增量模式（跳过未修改的文件）
        filter_ftl: 是否过滤 FTL 本地化键（默认开启）
    
    返回统计信息。
    """
    if fields is None:
        fields = DEFAULT_TRANSLATABLE_FIELDS
        
    yaml_processor = YAMLProcessor()
    extracted_data: List[Dict] = []
    
    # 统计信息
    stats = {
        "files_scanned": 0,
        "files_with_text": 0,
        "files_skipped": 0,  # 增量模式下跳过的文件数
        "ftl_skipped": 0,    # FTL 键过滤跳过的条目数
        "total_strings": 0,
        "by_field": {f: 0 for f in fields}
    }
    
    # 增量模式：加载哈希缓存和已有提取结果
    cache_file = os.path.join(os.path.dirname(output_file) or '.', HASH_CACHE_FILE)
    hash_cache: Dict[str, str] = {}
    existing_data: Dict[str, Dict] = {}  # key -> entry
    
    if incremental:
        log("📊 增量模式已启用，将跳过未修改的文件")
        hash_cache = load_hash_cache(cache_file)
        
        # 加载已有的提取结果
        if os.path.exists(output_file):
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    for entry in json.load(f):
                        existing_data[entry.get('key', '')] = entry
                log(f"已加载 {len(existing_data)} 条已有提取记录")
            except:
                pass
    
    new_hash_cache: Dict[str, str] = {}
    
    # 收集所有 YAML 文件
    yaml_files = []
    for root, dirs, files in os.walk(scan_dir):
        for file in files:
            if file.endswith('.yml') or file.endswith('.yaml'):
                yaml_files.append(os.path.join(root, file))
    
    total_files = len(yaml_files)
    log(f"正在扫描目录: {scan_dir} (共 {total_files} 个文件)")
    
    for i, file_path in enumerate(yaml_files):
        rel_path = os.path.relpath(file_path, scan_dir)
        stats["files_scanned"] += 1
        report_progress(i + 1, total_files, f"扫描: {rel_path}")
        
        # 增量模式：检查文件是否有变化
        if incremental:
            current_hash = compute_file_hash(file_path)
            new_hash_cache[rel_path] = current_hash
            
            if rel_path in hash_cache and hash_cache[rel_path] == current_hash:
                # 文件未修改，跳过扫描，但保留已有数据
                stats["files_skipped"] += 1
                continue
        
        try:
            data = yaml_processor.load(file_path)
            if not data:
                continue
            
            count_before = len(extracted_data)
            
            if isinstance(data, list):
                for node in data:
                    process_node_extract(node, extracted_data, rel_path, fields, stats, filter_ftl)
            elif isinstance(data, dict):
                process_node_extract(data, extracted_data, rel_path, fields, stats, filter_ftl)
            
            if len(extracted_data) > count_before:
                stats["files_with_text"] += 1
                 
        except Exception as e:
            log(f"解析文件错误 {file_path}: {e}", "WARNING")

    # 增量模式：合并已有数据和新数据
    if incremental and existing_data:
        # 构建新数据的 key 集合
        new_keys = {entry['key'] for entry in extracted_data}
        
        # 保留未被重新扫描的文件中的数据
        for key, entry in existing_data.items():
            if key not in new_keys:
                # 检查该条目对应的文件是否被跳过（仍然存在）
                context = entry.get('context', '')
                # 从 context 中提取文件路径
                if '文件:' in context:
                    file_line = context.split('\n')[0]
                    file_path = file_line.replace('文件:', '').strip()
                    if file_path in new_hash_cache:
                        extracted_data.append(entry)
        
        log(f"增量合并后共 {len(extracted_data)} 条记录")

    stats["total_strings"] = len(extracted_data)
    
    log(f"提取完成。扫描 {stats['files_scanned']} 个文件，"
        f"跳过 {stats['files_skipped']} 个（未修改），"
        f"其中 {stats['files_with_text']} 个包含文本，"
        f"共 {stats['total_strings']} 条字符串。")
    
    if stats.get("translated", 0) > 0:
        log(f"  ✅ 已标记 {stats['translated']} 条为已翻译状态 (stage: 1)")
    
    if stats.get("ftl_skipped", 0) > 0:
        log(f"  ⚠️ 已过滤 {stats['ftl_skipped']} 条 FTL 本地化键")
    
    # 输出字段统计
    for field, count in stats["by_field"].items():
        if count > 0:
            log(f"  - {field}: {count} 条")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(extracted_data, f, indent=2, ensure_ascii=False)
    
    # 保存新的哈希缓存
    if incremental:
        save_hash_cache(cache_file, new_hash_cache)
        log(f"已更新文件哈希缓存: {cache_file}")
    
    log(f"已保存到 {output_file}")
    return stats

def process_node_extract(node: Dict, extracted_data: List, rel_path: str, 
                         fields: List[str], stats: Dict, filter_ftl: bool = True):
    """
    提取单个节点中的文本。
    
    参数:
        filter_ftl: 是否过滤 FTL 本地化键（默认开启）
    """
    if not isinstance(node, dict):
        return
        
    entity_type = node.get('type')
    entity_id = node.get('id')
    parent = node.get('parent')
    
    if entity_type == 'entity' or 'id' in node:
        if entity_id:
            key_prefix = entity_id
        elif parent:
            p_str = parent[0] if isinstance(parent, list) and parent else str(parent)
            key_prefix = f"Parent_{p_str}"
            if node.get('suffix'):
                key_prefix += f"_{node.get('suffix')}"
        else:
            return 

        for field in fields:
            if field in node and isinstance(node[field], str):
                original_text = node[field]
                if not original_text.strip():
                    continue
                
                # FTL 键过滤：跳过形如 "loadout-group-weapon" 的本地化引用
                if filter_ftl and is_ftl_key(original_text):
                    stats["ftl_skipped"] = stats.get("ftl_skipped", 0) + 1
                    continue
                
                key = f"{key_prefix}.{field}"
                
                context = f"文件: {rel_path}\n"
                if entity_id:
                    context += f"ID: {entity_id}\n"
                if parent:
                    context += f"Parent: {parent}\n"
                
                # 构建词条数据
                entry = {
                    "key": key,
                    "original": original_text,
                    "context": context
                }
                
                # 如果包含中文，添加翻译状态 (stage: 1 = 已翻译)
                if contains_chinese(original_text):
                    entry["translation"] = original_text
                    entry["stage"] = 1
                    stats["translated"] = stats.get("translated", 0) + 1
                
                extracted_data.append(entry)
                
                stats["by_field"][field] = stats["by_field"].get(field, 0) + 1

# ==================== 按文件夹分组提取 (Folder-Based Extraction) ====================

from collections import defaultdict
import glob

def extract_strings_by_folder(scan_dir: str, output_dir: str, fields: List[str] = None,
                               filter_ftl: bool = True) -> Dict[str, int]:
    """
    按文件夹结构提取，每个文件夹生成一个 JSON 文件，保留完整目录结构。
    
    参数:
        scan_dir: 扫描目录
        output_dir: 输出目录（存放多个 JSON 文件）
        fields: 要提取的字段列表
        filter_ftl: 是否过滤 FTL 本地化键
    
    返回统计信息。
    """
    if fields is None:
        fields = DEFAULT_TRANSLATABLE_FIELDS
    
    yaml_processor = YAMLProcessor()
    
    # 按文件夹分组的数据
    folder_data: Dict[str, List[Dict]] = defaultdict(list)
    
    # 统计信息
    stats = {
        "files_scanned": 0,
        "files_with_text": 0,
        "ftl_skipped": 0,
        "total_strings": 0,
        "folder_count": 0,
        "by_field": {f: 0 for f in fields}
    }
    
    # 收集所有 YAML 文件
    yaml_files = []
    for root, dirs, files in os.walk(scan_dir):
        for file in files:
            if file.endswith('.yml') or file.endswith('.yaml'):
                yaml_files.append(os.path.join(root, file))
    
    total_files = len(yaml_files)
    log(f"📂 按文件夹分组模式：扫描 {scan_dir} (共 {total_files} 个文件)")
    
    for i, file_path in enumerate(yaml_files):
        rel_path = os.path.relpath(file_path, scan_dir)
        stats["files_scanned"] += 1
        report_progress(i + 1, total_files, f"扫描: {rel_path}")
        
        # 计算分组键（使用完整文件夹路径，用 / 分隔）
        folder = os.path.dirname(rel_path).replace('\\', '/')
        
        # 使用完整路径作为分组键，空路径使用 "root"
        group_key = folder if folder else "root"
        
        try:
            file_size = os.path.getsize(file_path)
            data = yaml_processor.load(file_path)
            if not data:
                continue
            
            # 临时存储本文件提取的数据
            file_entries: List[Dict] = []
            file_stats = {"ftl_skipped": 0, "by_field": {f: 0 for f in fields}}
            
            if isinstance(data, list):
                for node in data:
                    process_node_extract(node, file_entries, rel_path, fields, file_stats, filter_ftl)
            elif isinstance(data, dict):
                process_node_extract(data, file_entries, rel_path, fields, file_stats, filter_ftl)
            
            if file_entries:
                folder_data[group_key].extend(file_entries)
                stats["files_with_text"] += 1
                log(f"  + [{len(file_entries)}条] {rel_path} ({file_size/1024:.1f}KB)", "DEBUG")
            
            # 累计统计
            stats["ftl_skipped"] += file_stats.get("ftl_skipped", 0)
            for field, count in file_stats["by_field"].items():
                stats["by_field"][field] = stats["by_field"].get(field, 0) + count
                
        except Exception as e:
            log(f"解析文件错误 {file_path}: {e}", "WARNING")
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 为每个分组生成 JSON 文件（保持目录结构）
    for group_name, entries in folder_data.items():
        if not entries:
            continue
        
        # group_name 格式如 "Entities/Clothing" 或 "root"
        if group_name == "root":
            output_file = os.path.join(output_dir, "root.json")
        else:
            # 创建子目录结构
            # Entities/Clothing -> output_dir/Entities/Clothing.json
            parent_dir = os.path.dirname(group_name)
            base_name = os.path.basename(group_name)
            
            if parent_dir:
                full_parent = os.path.join(output_dir, parent_dir)
                os.makedirs(full_parent, exist_ok=True)
                output_file = os.path.join(full_parent, f"{base_name}.json")
            else:
                output_file = os.path.join(output_dir, f"{base_name}.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
        
        stats["total_strings"] += len(entries)
        stats["folder_count"] += 1
        log(f"  📄 {group_name}.json: {len(entries)} 条")
    
    log(f"✅ 提取完成。扫描 {stats['files_scanned']} 个文件，"
        f"生成 {stats['folder_count']} 个 JSON 文件，"
        f"共 {stats['total_strings']} 条字符串。")
    
    if stats.get("ftl_skipped", 0) > 0:
        log(f"  ⚠️ 已过滤 {stats['ftl_skipped']} 条 FTL 本地化键")
    
    return stats

# ==================== 合并逻辑 (Merge Logic) ====================

def merge_translations(repo_root: str, translation_file: str, output_dir: str, 
                       fields: List[str] = None) -> Dict[str, int]:
    """
    将 JSON 中的翻译合并到 repo_root 下的 YAML 文件中。
    返回统计信息。
    """
    if fields is None:
        fields = DEFAULT_TRANSLATABLE_FIELDS
        
    yaml_processor = YAMLProcessor()
    
    # 统计信息
    stats = {
        "files_modified": 0,
        "strings_applied": 0,
        "strings_skipped": 0,
        "translations_unused": 0
    }
    
    if not os.path.exists(translation_file):
        log(f"未找到翻译文件: {translation_file}", "ERROR")
        return stats

    with open(translation_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)
        
    translation_map: Dict[str, str] = {}
    if isinstance(raw_data, list):
        for item in raw_data:
            start_key = item.get('key')
            translation = item.get('translation', '')
            if start_key and translation:
                translation_map[start_key] = translation
    elif isinstance(raw_data, dict):
        translation_map = raw_data
    
    used_keys = set()
    log(f"已加载 {len(translation_map)} 条翻译。")
    
    # 收集所有 YAML 文件
    yaml_files = []
    for root, dirs, files in os.walk(repo_root):
        for file in files:
            if file.endswith('.yml') or file.endswith('.yaml'):
                yaml_files.append(os.path.join(root, file))
    
    total_files = len(yaml_files)
    log(f"读取目录: {repo_root} (共 {total_files} 个文件)")
    log(f"写入目录: {output_dir}")
    
    for i, file_path in enumerate(yaml_files):
        rel_path = os.path.relpath(file_path, repo_root)
        report_progress(i + 1, total_files, f"合并: {rel_path}")
        
        try:
            data = yaml_processor.load(file_path)
            if not data:
                continue
            
            modified = False
            
            if isinstance(data, list):
                for node in data:
                    result = process_node_merge(node, translation_map, fields, used_keys)
                    if result["modified"]:
                        modified = True
                    stats["strings_applied"] += result["applied"]
                    stats["strings_skipped"] += result["skipped"]
            elif isinstance(data, dict):
                result = process_node_merge(data, translation_map, fields, used_keys)
                if result["modified"]:
                    modified = True
                stats["strings_applied"] += result["applied"]
                stats["strings_skipped"] += result["skipped"]
            
            if modified:
                out_path = os.path.join(output_dir, rel_path)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                yaml_processor.dump(data, out_path)
                stats["files_modified"] += 1
                
        except Exception as e:
            log(f"处理文件错误 {file_path}: {e}", "WARNING")
    
    stats["translations_unused"] = len(translation_map) - len(used_keys)
    
    log(f"合并完成。修改了 {stats['files_modified']} 个文件，"
        f"应用了 {stats['strings_applied']} 条翻译，"
        f"跳过 {stats['strings_skipped']} 条（内容相同），"
        f"未使用 {stats['translations_unused']} 条。")
    
    return stats

def process_node_merge(node: Dict, translation_map: Dict[str, str], 
                       fields: List[str], used_keys: set) -> Dict[str, Any]:
    """合并单个节点中的翻译"""
    result = {"modified": False, "applied": 0, "skipped": 0}
    
    if not isinstance(node, dict):
        return result
        
    entity_id = node.get('id')
    parent = node.get('parent')
    
    if 'id' in node or node.get('type') == 'entity':
        if entity_id:
            key_prefix = entity_id
        elif parent:
            p_str = parent[0] if isinstance(parent, list) and parent else str(parent)
            key_prefix = f"Parent_{p_str}"
            if node.get('suffix'):
                key_prefix += f"_{node.get('suffix')}"
        else:
            return result

        for field in fields:
            if field in node:
                key = f"{key_prefix}.{field}"
                if key in translation_map:
                    used_keys.add(key)
                    new_text = translation_map[key]
                    if new_text and new_text != node[field]:
                        node[field] = new_text
                        result["modified"] = True
                        result["applied"] += 1
                    else:
                        result["skipped"] += 1
                         
    return result

# ==================== 一键工作流 (One-Click Workflow) ====================

def run_full_workflow(scan_dir: str, output_json: str, translation_json: str,
                      project_id: int, token: str, output_dir: str,
                      fields: List[str] = None, by_folder: bool = False,
                      filter_ftl: bool = True, incremental: bool = False) -> bool:
    """
    执行完整的汉化工作流：提取 → 上传 → 下载 → 合并
    
    参数:
        by_folder: 是否按文件夹分组模式（生成多个 JSON）
        filter_ftl: 是否过滤 FTL 键
    """
    log("=" * 50)
    log("开始执行一键工作流")
    if by_folder:
        log("📂 模式: 按文件夹分组")
    else:
        log("📄 模式: 单文件")
    log("=" * 50)
    
    # 步骤 1: 提取
    log("\n[步骤 1/4] 提取原文...")
    try:
        if by_folder:
            # 分组模式：输出到目录
            extract_strings_by_folder(scan_dir, output_json, fields, 
                                      filter_ftl=filter_ftl)
        else:
            # 单文件模式
            extract_strings(scan_dir, output_json, fields, 
                           incremental=incremental, filter_ftl=filter_ftl)
    except Exception as e:
        log(f"提取失败: {e}", "ERROR")
        return False
    
    # 步骤 2: 上传
    log("\n[步骤 2/4] 上传到 Paratranz...")
    try:
        client = PZClient(project_id, token)
        if not client.test_connection():
            log("API 连接测试失败，终止工作流", "ERROR")
            return False
        
        if by_folder:
            # 分组模式：批量上传目录
            result = client.upload_folder(output_json)
            if result.get("failed", 0) > result.get("uploaded", 0):
                log("批量上传失败过多，终止工作流", "ERROR")
                return False
        else:
            # 单文件模式
            if not client.upload_file(output_json):
                log("上传失败，终止工作流", "ERROR")
                return False
    except Exception as e:
        log(f"上传失败: {e}", "ERROR")
        return False
    
    # 步骤 3: 下载
    log("\n[步骤 3/4] 从 Paratranz 下载翻译...")
    try:
        if not client.download_file(translation_json, os.path.basename(output_json)):
            log("下载失败，终止工作流", "ERROR")
            return False
    except Exception as e:
        log(f"下载失败: {e}", "ERROR")
        return False
    
    # 步骤 4: 合并
    log("\n[步骤 4/4] 合并翻译...")
    try:
        merge_translations(scan_dir, translation_json, output_dir, fields)
    except Exception as e:
        log(f"合并失败: {e}", "ERROR")
        return False
    
    log("\n" + "=" * 50)
    log("✅ 一键工作流执行完成！")
    log("=" * 50)
    return True

# ==================== 图形界面 (GUI) ====================

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SS14 自动化汉化工具箱 v3.2")
        self.root.geometry("1100x800")
        self.root.minsize(1050, 700)
        
        # 加载配置
        self.config = self.load_config()
        self.is_running = False
        self.stop_requested = False

        # 注册 GUI 日志回调
        gui_log_handler.set_callback(self.update_gui_log)

        # 设置现代化样式主题
        self._setup_styles()
        
        # 设置窗口背景色
        self.root.configure(bg=self.colors['bg'])
        
        # === 创建可滚动的主容器 ===
        # 外层容器
        outer_frame = ttk.Frame(self.root)
        outer_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建 Canvas 和滚动条
        self.canvas = tk.Canvas(outer_frame, bg=self.colors['bg'], highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=self.canvas.yview)
        
        # 可滚动的内部 Frame
        self.scrollable_frame = ttk.Frame(self.canvas, style='Main.TFrame')
        
        # 当内容变化时更新滚动区域
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        
        # 在 Canvas 中创建窗口
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        
        # 当 Canvas 大小变化时，调整内部 Frame 宽度
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        
        # 配置滚动条
        self.canvas.configure(yscrollcommand=scrollbar.set)
        
        # 布局
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 绑定鼠标滚轮事件
        self._bind_mousewheel()
        
        # 构建主界面内容
        self._build_ui()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # 自动检测目录
        self.auto_detect_directory()

    def _setup_styles(self):
        """配置现代化的UI样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # === 颜色定义 (Slate/Blue Theme) ===
        self.colors = {
            'primary': '#1890ff',       # 主色 - 科技蓝
            'primary_hover': '#40a9ff',
            'primary_dark': '#096dd9',  # 兼容旧代码
            'success': '#52c41a',       # 成功 - 鲜绿
            'success_hover': '#73d13d',
            'success_dark': '#389e0d',  # 兼容旧代码
            'warning': '#faad14',       # 警告 - 金黄
            'warning_hover': '#ffc53d',
            'danger': '#ff4d4f',        # 危险 - 红色
            'danger_hover': '#ff7875',
            'bg': '#f0f2f5',            # 全局背景 - 浅灰
            'card_bg': '#ffffff',       # 卡片背景 - 纯白
            'text': '#262626',          # 主文本 - 深黑
            'text_secondary': '#595959',# 次要文本 - 灰
            'text_muted': '#8c8c8c',    # 兼容旧代码 (提示文本)
            'text_hint': '#8c8c8c',     # 提示文本
            'border': '#d9d9d9',        # 边框
            'input_bg': '#ffffff',      # 输入框背景
        }
        
        # === 字体定义 ===
        base_font = 'Microsoft YaHei UI' if sys.platform == 'win32' else 'Helvetica'
        self.fonts = {
            'h1': (base_font, 18, 'bold'),
            'h2': (base_font, 14, 'bold'),
            'body': (base_font, 10),
            'body_bold': (base_font, 10, 'bold'),
            'small': (base_font, 9),
            'mono': ('Consolas', 10),
        }
        
        # 兼容旧代码的字体引用
        self.default_font = self.fonts['body']
        self.default_font_bold = self.fonts['body_bold']
        self.title_font = self.fonts['h1']
        self.mono_font = self.fonts['mono']
        
        # === 样式配置 ===
        
        # 基础 Frame 和 Label
        style.configure('.', background=self.colors['bg'], foreground=self.colors['text'], font=self.fonts['body'])
        style.configure('Main.TFrame', background=self.colors['bg'])
        style.configure('Card.TFrame', background=self.colors['card_bg'], relief='flat')
        
        # Label 样式
        style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['text'])
        style.configure('Card.TLabel', background=self.colors['card_bg'], foreground=self.colors['text'])
        style.configure('Title.TLabel', font=self.fonts['h1'], background=self.colors['bg'])
        style.configure('CardTitle.TLabel', font=self.fonts['h2'], background=self.colors['card_bg'], foreground=self.colors['text'])
        style.configure('Hint.TLabel', background=self.colors['card_bg'], foreground=self.colors['text_hint'], font=self.fonts['small'])
        style.configure('Card.TCheckbutton', background=self.colors['card_bg'], font=self.fonts['body'])
        
        # 按钮通用样式
        style.configure('TButton', font=self.fonts['body'], padding=[15, 8], borderwidth=0, relief='flat')
        
        # 主要按钮 (Primary)
        style.configure('Primary.TButton', 
                        background=self.colors['primary'], 
                        foreground='white',
                        font=self.fonts['body_bold'],
                        padding=[30, 12])  # 加大按钮
        style.map('Primary.TButton',
                  background=[('active', self.colors['primary_hover']), ('pressed', self.colors['primary_hover'])])
        
        # 成功按钮 (Success)
        style.configure('Success.TButton', 
                        background=self.colors['success'], 
                        foreground='white',
                        font=self.fonts['body_bold'],
                        padding=[25, 12])  # 加大按钮
        style.map('Success.TButton',
                  background=[('active', self.colors['success_hover']), ('pressed', self.colors['success_hover'])])
        
        # 警告按钮 (Warning)
        style.configure('Warning.TButton', 
                        background=self.colors['warning'], 
                        foreground='white',
                        font=self.fonts['body_bold'],
                        padding=[25, 12])  # 加大按钮
        style.map('Warning.TButton',
                  background=[('active', self.colors['warning_hover']), ('pressed', self.colors['warning_hover'])])

        # 危险按钮 (Danger)
        style.configure('Danger.TButton', 
                        background=self.colors['danger'], 
                        foreground='white',
                        font=self.fonts['body_bold'],
                        padding=[20, 10])
        style.map('Danger.TButton',
                  background=[('active', self.colors['danger_hover']), ('pressed', self.colors['danger_hover'])])
        
        # 输入框 Entry
        style.configure('TEntry', fieldbackground=self.colors['input_bg'], padding=[10, 8], borderwidth=1, relief='solid')
        style.map('TEntry', bordercolor=[('focus', self.colors['primary'])], lightcolor=[('focus', self.colors['primary'])])
        
        # 下拉框 Combobox
        style.configure('TCombobox', fieldbackground=self.colors['input_bg'], padding=[10, 8], arrowsize=15)
        
        # 进度条
        style.configure('Horizontal.TProgressbar', background=self.colors['primary'], troughcolor='#e8e8e8', borderwidth=0)
        
        # 选项卡 Notebook
        style.configure('TNotebook', background=self.colors['bg'], tabmargins=[10, 10, 0, 0], borderwidth=0)
        style.configure('TNotebook.Tab', padding=[10, 8], font=self.fonts['body'], background='#e0e0e0', foreground=self.colors['text_secondary'], width=20, anchor='center')  # 固定宽度和居中
        style.map('TNotebook.Tab',
                  background=[('selected', self.colors['card_bg'])],
                  foreground=[('selected', self.colors['primary'])],
                  expand=[('selected', [0, 0, 0, 0])])

        # Labelframe (兼容旧代码，作为卡片容器)
        style.configure('TLabelframe', background=self.colors['card_bg'], relief='flat')
        style.configure('TLabelframe.Label', background=self.colors['card_bg'], font=self.fonts['h2'], foreground=self.colors['text'])

    def _create_card(self, parent, title=None):
        """创建一个卡片容器"""
        card = ttk.Frame(parent, style='Card.TFrame', padding=20)
        if title:
            ttk.Label(card, text=title, style='CardTitle.TLabel').pack(anchor='w', pady=(0, 15))
        return card

    def _build_ui(self):
        """构建整体 UI 结构"""
        main_frame = self.scrollable_frame
        
        # === 顶部标题栏 ===
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(20, 20), padx=20)
        
        # 使用安全的 Unicode 字符作为图标
        icon_label = ttk.Label(header_frame, text="\U0001F6E0", font=("Microsoft YaHei UI", 32)) # 🛠️
        icon_label.pack(side=tk.LEFT, padx=(0, 15))
        
        title_box = ttk.Frame(header_frame)
        title_box.pack(side=tk.LEFT)
        ttk.Label(title_box, text="SS14 汉化工作流工具", style='Title.TLabel').pack(anchor='w')
        ttk.Label(title_box, text="v3.2 | 自动化提取与同步助手", font=self.fonts['small'], foreground=self.colors['text_secondary']).pack(anchor='w')
        
        # === 状态与进度卡片 ===
        status_card = self._create_card(main_frame, "运行状态")
        status_card.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(status_card, variable=self.progress_var, maximum=100, style='Horizontal.TProgressbar')
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        # 状态文本行
        status_row = ttk.Frame(status_card, style='Card.TFrame')
        status_row.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="当前就绪")
        ttk.Label(status_row, text="状态:", style='Card.TLabel', font=self.fonts['body_bold']).pack(side=tk.LEFT)
        self.progress_label = ttk.Label(status_row, textvariable=self.status_var, style='Card.TLabel', foreground=self.colors['primary'])
        self.progress_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 停止按钮容器
        self.stop_frame = ttk.Frame(status_row, style='Card.TFrame')
        self.btn_stop = ttk.Button(self.stop_frame, text="⏹ 停止运行", command=self.do_stop, style='Danger.TButton')
        self.btn_stop.pack(side=tk.RIGHT)
        
        # 一键工作流卡片 (移动到 Tabs 上方)
        self._build_workflow_card(main_frame)
        
        # === 核心功能区 (Notebook) ===
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # 创建标签页
        self.tab_extract = ttk.Frame(self.notebook, style='Main.TFrame')
        self.notebook.add(self.tab_extract, text="  提取原文  ")
        self.setup_extract_tab()
        
        self.tab_sync = ttk.Frame(self.notebook, style='Main.TFrame')
        self.notebook.add(self.tab_sync, text="  Paratranz 同步  ")
        self.setup_sync_tab()
        
        self.tab_merge = ttk.Frame(self.notebook, style='Main.TFrame')
        self.notebook.add(self.tab_merge, text="  合并翻译  ")
        self.setup_merge_tab()
        
        self.tab_settings = ttk.Frame(self.notebook, style='Main.TFrame')
        self.notebook.add(self.tab_settings, text="  设置  ")
        self.setup_settings_tab()
        
        # === 日志区域 ===
        log_card = self._create_card(main_frame, "运行日志")
        log_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))
        
        self.log_text = scrolledtext.ScrolledText(
            log_card, height=12, state='disabled',
            font=self.fonts['mono'],
            bg='#1e272e', fg='#dfe6e9',
            insertbackground='white',
            relief='flat', padx=10, pady=10
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # 配置日志颜色标签
        self.log_text.tag_configure('success', foreground='#00b894')
        self.log_text.tag_configure('error', foreground='#ff7675')
        self.log_text.tag_configure('warning', foreground='#fdcb6e')
        self.log_text.tag_configure('info', foreground='#74b9ff')

    def _build_workflow_card(self, parent):
        """构建一键工作流卡片"""
        card = self._create_card(parent)
        card.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        # 左右布局
        left_side = ttk.Frame(card, style='Card.TFrame')
        left_side.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        ttk.Label(left_side, text="⚡ 一键自动化工作流", style='CardTitle.TLabel', foreground=self.colors['primary']).pack(anchor='w')
        desc = "自动按顺序执行：提取原文 → 上传到 Paratranz → 下载最新翻译 → 合并回游戏文件。\n适合日常同步更新使用。"
        ttk.Label(left_side, text=desc, style='Card.TLabel', foreground=self.colors['text_secondary']).pack(anchor='w', pady=(5, 0))
        
        right_side = ttk.Frame(card, style='Card.TFrame')
        right_side.pack(side=tk.RIGHT, padx=(20, 0))
        
        self.btn_workflow = ttk.Button(right_side, text="开始一键同步", command=self.do_full_workflow, style='Primary.TButton')
        self.btn_workflow.pack()

    def auto_detect_directory(self):
        """启动时自动检测游戏目录"""
        detected = detect_game_directory()
        if detected:
            self.extract_dir_var.set(detected)
            self.merge_source_var.set(detected)
            self.log(f"自动检测到游戏目录: {detected}")

    def _on_canvas_configure(self, event):
        """当 Canvas 大小变化时，调整内部 Frame 宽度以匹配"""
        self.canvas.itemconfig(self.canvas_window, width=event.width)
    
    def _bind_mousewheel(self):
        """绑定鼠标滚轮事件（跨平台支持）"""
        # 直接绑定到 root 窗口，确保在任何位置都能响应滚轮
        self.root.bind("<MouseWheel>", self._on_mousewheel)
        self.root.bind("<Button-4>", self._on_mousewheel)  # Linux scroll up
        self.root.bind("<Button-5>", self._on_mousewheel)  # Linux scroll down
        
        # 同时也绑定到 canvas 和 scrollable_frame
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.scrollable_frame.bind("<MouseWheel>", self._on_mousewheel)
        
        # 递归绑定所有子控件
        self.root.after(100, self._bind_children_mousewheel)
    
    def _bind_children_mousewheel(self):
        """递归给所有子控件绑定鼠标滚轮事件"""
        def bind_recursive(widget):
            try:
                widget.bind("<MouseWheel>", self._on_mousewheel)
                widget.bind("<Button-4>", self._on_mousewheel)
                widget.bind("<Button-5>", self._on_mousewheel)
            except:
                pass
            for child in widget.winfo_children():
                bind_recursive(child)
        
        bind_recursive(self.scrollable_frame)
    
    def _on_mousewheel(self, event):
        """处理鼠标滚轮滚动"""
        # 检查 canvas 是否存在且内容是否超出视口
        try:
            bbox = self.canvas.bbox("all")
            if bbox:
                canvas_height = self.canvas.winfo_height()
                content_height = bbox[3] - bbox[1]
                
                # 只在内容超出视口时滚动
                if content_height > canvas_height:
                    # Windows/MacOS
                    if hasattr(event, 'delta') and event.delta != 0:
                        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
                    # Linux scroll up
                    elif event.num == 4:
                        self.canvas.yview_scroll(-1, "units")
                    # Linux scroll down
                    elif event.num == 5:
                        self.canvas.yview_scroll(1, "units")
        except:
            pass

    def load_config(self) -> Dict:
        default_config = {
            "extract_dir": "Resources/Prototypes",
            "extract_output": "en.json",
            "pz_token": "",
            "pz_project_id": "16648",
            "merge_source": "Resources/Prototypes",
            "merge_input": "zh.json",
            "download_path": "zh.json",
            "upload_path": "",  # 新增：自定义上传路径
            "translatable_fields": DEFAULT_TRANSLATABLE_FIELDS,
            # 路径历史记录
            "history_extract_dir": [],
            "history_extract_output": [],
            "history_download_path": [],
            "history_upload_path": [],  # 新增
            "history_merge_input": [],
            "history_merge_source": []
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return {**default_config, **json.load(f)}
            except:
                return default_config
        return default_config

    def save_config(self):
        self.config["extract_dir"] = self.extract_dir_var.get()
        self.config["extract_output"] = self.extract_output_var.get()
        self.config["pz_token"] = self.pz_token_var.get()
        self.config["pz_project_id"] = self.pz_project_id_var.get()
        self.config["merge_source"] = self.merge_source_var.get()
        self.config["merge_input"] = self.merge_input_var.get()
        self.config["download_path"] = self.download_path_var.get()
        if hasattr(self, 'upload_path_var'):
            self.config["upload_path"] = self.upload_path_var.get()
        self.config["translatable_fields"] = [f.strip() for f in self.fields_var.get().split(',')]
        # 新增选项
        self.config["filter_ftl"] = self.filter_ftl_var.get()
        self.config["by_folder"] = self.by_folder_var.get()
        
        # 保存路径历史记录（从各个 Combobox 获取）
        if hasattr(self, 'combo_extract_dir'):
            self.config["history_extract_dir"] = list(self.combo_extract_dir['values'])
        if hasattr(self, 'combo_extract_output'):
            self.config["history_extract_output"] = list(self.combo_extract_output['values'])
        if hasattr(self, 'combo_download_path'):
            self.config["history_download_path"] = list(self.combo_download_path['values'])
        if hasattr(self, 'combo_upload_path'):
            self.config["history_upload_path"] = list(self.combo_upload_path['values'])
        if hasattr(self, 'combo_merge_input'):
            self.config["history_merge_input"] = list(self.combo_merge_input['values'])
        if hasattr(self, 'combo_merge_source'):
            self.config["history_merge_source"] = list(self.combo_merge_source['values'])
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=4, ensure_ascii=False)

    def on_close(self):
        self.save_config()
        self.root.destroy()

    def update_gui_log(self):
        """从队列中获取日志并更新到 GUI"""
        logs = gui_log_handler.pop_logs()
        if not logs:
            return
            
        def _update():
            try:
                self.log_text.config(state='normal')
                for levelname, message in logs:
                    tag = None
                    if levelname in ['ERROR', 'CRITICAL'] or '❌' in message or 'Error' in message:
                        tag = 'error'
                    elif levelname == 'WARNING' or '⚠️' in message or 'Warning' in message:
                        tag = 'warning'
                    elif '✅' in message or '成功' in message or '完成' in message:
                        tag = 'success'
                    elif 'INFO' in message or 'ℹ️' in message or '📂' in message or '📄' in message:
                        tag = 'info'
                    
                    if tag:
                        self.log_text.insert(tk.END, message + "\n", tag)
                    else:
                        self.log_text.insert(tk.END, message + "\n")
                
                # 限制缓冲区大小 (约 5000 行)
                try:
                    index = self.log_text.index('end-1c')
                    line_count = int(index.split('.')[0])
                    if line_count > 5000:
                        self.log_text.delete('1.0', f'{line_count - 5000}.0')
                except Exception:
                    pass
                
                self.log_text.see(tk.END)
            except Exception:
                pass
            finally:
                self.log_text.config(state='disabled')
            
        self.root.after(0, _update)

    def log(self, message: str, level: str = "INFO"):
        """输出日志 (代理到全局 logging)"""
        log(message, level)

    def update_progress(self, current: int, total: int, message: str = ""):
        def _update():
            if total > 0:
                percent = (current / total) * 100
                self.progress_var.set(percent)
                self.progress_label.config(text=f"{current}/{total} - {message[:30]}")
        self.root.after(0, _update)

    def run_in_thread(self, func, *args, success_msg="操作成功完成！"):
        """在后台线程中运行函数"""
        if self.is_running:
            messagebox.showwarning("提示", "有操作正在进行中，请稍候...")
            return
        
        def _show_stop_button():
            """显示停止按钮"""
            self.stop_frame.pack(fill=tk.X, pady=(10, 0))
        
        def _hide_stop_button():
            """隐藏停止按钮"""
            self.stop_frame.pack_forget()
            
        def _run():
            self.is_running = True
            self.stop_requested = False
            self.status_var.set("正在运行...")
            self.progress_var.set(0)
            
            # 显示停止按钮
            self.root.after(0, _show_stop_button)
            
            # 设置进度回调和停止检查回调
            set_progress_callback(self.update_progress)
            set_stop_check_callback(lambda: self.stop_requested)
            
            try:
                result = func(*args)
                
                if self.stop_requested:
                    self.log("⏹ 操作已被用户停止")
                    self.status_var.set("已停止")
                elif result is False:
                    self.log("❌ 操作失败，请检查上方日志。")
                    self.status_var.set("操作失败")
                    self.root.after(0, lambda: messagebox.showerror("错误", "操作过程中发生错误，请查看日志。"))
                else:
                    self.log(f"✅ {success_msg}")
                    self.status_var.set("操作成功")
                    self.progress_var.set(100)
                    self.root.after(0, lambda: messagebox.showinfo("成功", success_msg))
                    
            except Exception as e:
                if self.stop_requested:
                    self.log("⏹ 操作已被用户停止")
                    self.status_var.set("已停止")
                else:
                    self.log(f"❌ 发生异常: {str(e)}")
                    self.status_var.set("发生错误")
                    self.root.after(0, lambda: messagebox.showerror("错误", f"运行异常: {e}"))
            finally:
                self.is_running = False
                self.stop_requested = False
                set_progress_callback(None)
                set_stop_check_callback(None)
                # 隐藏停止按钮
                self.root.after(0, _hide_stop_button)

        threading.Thread(target=_run, daemon=True).start()

    def do_stop(self):
        """请求停止当前操作"""
        if self.is_running:
            self.stop_requested = True
            self.log("⏳ 正在停止，请稍候...")
            self.status_var.set("正在停止...")

    # ===== 界面设置 =====

    def setup_extract_tab(self):
        frame = self.tab_extract
        
        # 输入区域容器
        input_card = self._create_card(frame, '📁 路径设置')
        input_card.pack(fill=tk.X, pady=(0, 20))
        
        # 扫描目录
        row1 = ttk.Frame(input_card, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="扫描目录:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.extract_dir_var = tk.StringVar(value=self.config["extract_dir"])
        self.combo_extract_dir = ttk.Combobox(row1, textvariable=self.extract_dir_var, width=50)
        self.combo_extract_dir['values'] = self.config.get("history_extract_dir", [])
        self.combo_extract_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_extract_dir.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_extract_dir, self.extract_dir_var))
        ttk.Button(row1, text="浏览...", 
            command=lambda: self.select_folder(self.extract_dir_var, self.combo_extract_dir)).pack(side=tk.LEFT)
        
        # 输出文件/目录
        row2 = ttk.Frame(input_card, style='Card.TFrame')
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text="输出文件/目录:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.extract_output_var = tk.StringVar(value=self.config["extract_output"])
        self.combo_extract_output = ttk.Combobox(row2, textvariable=self.extract_output_var, width=50)
        self.combo_extract_output['values'] = self.config.get("history_extract_output", [])
        self.combo_extract_output.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_extract_output.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_extract_output, self.extract_output_var))
        ttk.Button(row2, text="浏览...", command=self._select_extract_output).pack(side=tk.LEFT)
        
        # 提示标签
        ttk.Label(input_card, text="💡 右键点击输入框可管理历史记录", 
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 0))
        
        # 选项区域
        options_card = self._create_card(frame, "⚙️ 提取选项")
        options_card.pack(fill=tk.X, pady=(0, 20))
        
        # FTL 过滤选项
        self.filter_ftl_var = tk.BooleanVar(value=self.config.get("filter_ftl", True))
        ttk.Checkbutton(options_card, text="过滤 FTL 本地化键值 (跳过 loadout-group-weapon 类)", 
                       variable=self.filter_ftl_var, style='Card.TCheckbutton').pack(anchor='w', pady=3)
        
        # 按文件夹分组选项
        self.by_folder_var = tk.BooleanVar(value=self.config.get("by_folder", False))
        ttk.Checkbutton(options_card, text="按文件夹分组提取 (保留完整目录结构，生成多个 JSON)", 
                       variable=self.by_folder_var, style='Card.TCheckbutton').pack(anchor='w', pady=3)
        
        # 按钮居中区域
        btn_frame = ttk.Frame(frame, style='Main.TFrame')
        btn_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(btn_frame, text="▶️ 开始提取", command=self.do_extract,
                   style='Primary.TButton').pack(anchor='center')

    def _select_extract_output(self):
        """选择提取输出位置（文件或目录）"""
        if self.by_folder_var.get():
            # 按文件夹模式：选择目录
            folder = filedialog.askdirectory(title="选择输出目录")
            if folder:
                self.extract_output_var.set(folder)
                self.add_to_history(self.combo_extract_output, folder)
        else:
            # 单文件模式：选择文件
            file = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                initialfile="en.json"
            )
            if file:
                self.extract_output_var.set(file)
                self.add_to_history(self.combo_extract_output, file)

    def setup_sync_tab(self):
        frame = self.tab_sync
        
        # API 设置区域
        api_card = self._create_card(frame, "\U0001F511 API 设置")
        api_card.pack(fill=tk.X, pady=(0, 20))
        
        # 项目 ID
        row1 = ttk.Frame(api_card, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="项目 ID:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.pz_project_id_var = tk.StringVar(value=self.config["pz_project_id"])
        ttk.Entry(row1, textvariable=self.pz_project_id_var, width=20).pack(side=tk.LEFT)
        ttk.Label(row1, text="(Paratranz 项目编号)", 
                  style='Hint.TLabel').pack(side=tk.LEFT, padx=(10, 0))
        
        # API Token
        row2 = ttk.Frame(api_card, style='Card.TFrame')
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text="API Token:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.pz_token_var = tk.StringVar(value=self.config["pz_token"])
        ttk.Entry(row2, textvariable=self.pz_token_var, width=50, show="*").pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 文件路径设置区域
        path_card = self._create_card(frame, "\U0001F4C1 文件路径")
        path_card.pack(fill=tk.X, pady=(0, 20))
        
        # 上传路径
        row3 = ttk.Frame(path_card, style='Card.TFrame')
        row3.pack(fill=tk.X, pady=5)
        ttk.Label(row3, text="上传文件/目录:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.upload_path_var = tk.StringVar(value=self.config.get("upload_path", ""))
        self.combo_upload_path = ttk.Combobox(row3, textvariable=self.upload_path_var, width=42)
        self.combo_upload_path['values'] = self.config.get("history_upload_path", [])
        self.combo_upload_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_upload_path.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_upload_path, self.upload_path_var))
        
        # 浏览按钮区域
        browse_frame = ttk.Frame(row3, style='Card.TFrame')
        browse_frame.pack(side=tk.LEFT)
        ttk.Button(browse_frame, text="📄 文件", width=7,
            command=self._select_upload_file).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(browse_frame, text="📁 目录", width=7,
            command=self._select_upload_folder).pack(side=tk.LEFT)
        
        # Download Path
        row4 = ttk.Frame(path_card, style='Card.TFrame')
        row4.pack(fill=tk.X, pady=5)
        ttk.Label(row4, text="下载保存路径:", width=14, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.download_path_var = tk.StringVar(value=self.config.get("download_path", "zh.json"))
        self.combo_download_path = ttk.Combobox(row4, textvariable=self.download_path_var, width=42)
        self.combo_download_path['values'] = self.config.get("history_download_path", [])
        self.combo_download_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_download_path.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_download_path, self.download_path_var))
        ttk.Button(row4, text="浏览...", command=self._select_download_path).pack(side=tk.LEFT)
        
        # Hint
        ttk.Label(path_card, text="💡 右键点击输入框可管理历史记录", 
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 0))
        
        # Buttons
        btn_frame = ttk.Frame(frame, style='Main.TFrame')
        btn_frame.pack(fill=tk.X, pady=10)
        
        btn_inner = ttk.Frame(btn_frame, style='Main.TFrame')
        btn_inner.pack(anchor='center')
        
        ttk.Button(btn_inner, text="🔗 测试连接", command=self.do_test_connection).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_inner, text="⬆️ 上传", command=self.do_upload,
                   style='Primary.TButton').pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_inner, text="⬇️ 下载", command=self.do_download,
                   style='Success.TButton').pack(side=tk.LEFT, padx=5)

    def _select_download_path(self):
        """选择下载保存位置"""
        file = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="zh.json"
        )
        if file:
            self.download_path_var.set(file)
            self.add_to_history(self.combo_download_path, file)

    def _select_upload_file(self):
        """选择要上传的文件"""
        file = filedialog.askopenfilename(
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file:
            self.upload_path_var.set(file)
            self.add_to_history(self.combo_upload_path, file)

    def _select_upload_folder(self):
        """选择要上传的目录"""
        folder = filedialog.askdirectory(title="选择包含 JSON 文件的目录")
        if folder:
            self.upload_path_var.set(folder)
            self.add_to_history(self.combo_upload_path, folder)

    def setup_merge_tab(self):
        frame = self.tab_merge
        
        # 文件设置区域
        file_card = self._create_card(frame, "\U0001F4C4 文件设置")
        file_card.pack(fill=tk.X, pady=(0, 20))
        
        # 翻译文件
        row1 = ttk.Frame(file_card, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="翻译文件:", width=12, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.merge_input_var = tk.StringVar(value=self.config["merge_input"])
        self.combo_merge_input = ttk.Combobox(row1, textvariable=self.merge_input_var, width=50)
        self.combo_merge_input['values'] = self.config.get("history_merge_input", [])
        self.combo_merge_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_merge_input.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_merge_input, self.merge_input_var))
        ttk.Button(row1, text="浏览...", 
            command=lambda: self.select_file(self.merge_input_var, self.combo_merge_input)).pack(side=tk.LEFT)
        
        # 目标目录
        row2 = ttk.Frame(file_card, style='Card.TFrame')
        row2.pack(fill=tk.X, pady=5)
        ttk.Label(row2, text="目标目录:", width=12, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.merge_source_var = tk.StringVar(value=self.config["merge_source"])
        self.combo_merge_source = ttk.Combobox(row2, textvariable=self.merge_source_var, width=50)
        self.combo_merge_source['values'] = self.config.get("history_merge_source", [])
        self.combo_merge_source.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        self.combo_merge_source.bind("<Button-3>", 
            lambda e: self.show_history_context_menu(e, self.combo_merge_source, self.merge_source_var))
        ttk.Button(row2, text="浏览...", 
            command=lambda: self.select_folder(self.merge_source_var, self.combo_merge_source)).pack(side=tk.LEFT)
        
        # 提示标签
        ttk.Label(file_card, text="💡 右键点击输入框可管理历史记录", 
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 0))
        
        # 警告区域
        warning_card = self._create_card(frame)
        warning_card.pack(fill=tk.X, pady=(0, 20))
        
        warning_label = ttk.Label(warning_card, 
            text="⚠️ 注意：合并操作会修改目标目录中的 YAML 文件，操作前建议备份！",
            foreground=self.colors['danger'],
            font=self.default_font_bold, style='Card.TLabel')
        warning_label.pack(anchor='center')
        
        # 按钮居中区域
        btn_frame = ttk.Frame(frame, style='Main.TFrame')
        btn_frame.pack(fill=tk.X, pady=15)
        
        ttk.Button(btn_frame, text="🔀 开始合并", command=self.do_merge,
                   style='Warning.TButton').pack(anchor='center')

    def setup_settings_tab(self):
        frame = self.tab_settings
        
        # 字段设置区域
        fields_card = self._create_card(frame, "\U0001F527 翻译字段设置")
        fields_card.pack(fill=tk.X, pady=(0, 20))
        
        row1 = ttk.Frame(fields_card, style='Card.TFrame')
        row1.pack(fill=tk.X, pady=5)
        ttk.Label(row1, text="可翻译字段:", width=12, anchor='e', style='Card.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        fields_str = ', '.join(self.config.get("translatable_fields", DEFAULT_TRANSLATABLE_FIELDS))
        self.fields_var = tk.StringVar(value=fields_str)
        ttk.Entry(row1, textvariable=self.fields_var, width=50).pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        ttk.Label(fields_card, text="💡 多个字段用逗号分隔，默认: name, description", 
                  style='Hint.TLabel').pack(anchor='w', pady=(5, 0))
        
        # 说明区域
        info_card = self._create_card(frame, "\U00002139\U0000FE0F 使用说明")
        info_card.pack(fill=tk.X, pady=(0, 20))
        
        info_text = """工作流程说明：
1. 提取原文：从游戏 YAML 文件中提取可翻译的文本
2. Paratranz 同步：将提取的文本上传到 Paratranz 平台进行翻译
3. 下载翻译：从 Paratranz 下载翻译完成的文本
4. 合并翻译：将翻译文本合并回游戏 YAML 文件

推荐使用「一键工作流」自动完成以上所有步骤。"""
        
        ttk.Label(info_card, text=info_text, justify='left',
                  style='Card.TLabel').pack(anchor='w')
        
        # 按钮居中区域
        btn_frame = ttk.Frame(frame, style='Main.TFrame')
        btn_frame.pack(fill=tk.X, pady=20)
        
        ttk.Button(btn_frame, text="💾 保存设置", command=self.save_config,
                   style='Primary.TButton').pack(anchor='center')

    def select_folder(self, var, combo=None):
        """选择文件夹，可选地更新到 Combobox 历史"""
        folder = filedialog.askdirectory()
        if folder:
            var.set(folder)
            if combo:
                self.add_to_history(combo, folder)

    def select_file(self, var, combo=None, filetypes=None):
        """选择文件，可选地更新到 Combobox 历史"""
        if filetypes is None:
            filetypes = [("JSON files", "*.json"), ("All files", "*.*")]
        file = filedialog.askopenfilename(filetypes=filetypes)
        if file:
            var.set(file)
            if combo:
                self.add_to_history(combo, file)

    def add_to_history(self, combo, value, max_items=15):
        """将新值添加到 Combobox 历史记录（最多保留 max_items 条）"""
        if not value or not value.strip():
            return
        value = value.strip()
        current_values = list(combo['values'])
        # 去重：如果已存在则移到最前面
        if value in current_values:
            current_values.remove(value)
        current_values.insert(0, value)
        # 限制最大数量
        combo['values'] = current_values[:max_items]

    def show_history_context_menu(self, event, combo, var):
        """显示右键菜单，用于管理历史记录"""
        menu = tk.Menu(self.root, tearoff=0)
        current_values = list(combo['values'])
        
        if not current_values:
            menu.add_command(label="(无历史记录)", state='disabled')
        else:
            menu.add_command(label="📋 历史记录", state='disabled')
            menu.add_separator()
            # 显示最多10条历史记录供选择
            for i, val in enumerate(current_values[:10]):
                display = val if len(val) < 50 else "..." + val[-47:]
                menu.add_command(label=f"  {display}", 
                               command=lambda v=val: var.set(v))
            if len(current_values) > 10:
                menu.add_command(label=f"  ...还有 {len(current_values) - 10} 条", state='disabled')
            
            menu.add_separator()
            menu.add_command(label="🗑️ 删除当前选中项", 
                           command=lambda: self.delete_history_item(combo, var.get()))
            menu.add_command(label="🗑️ 清空所有历史", 
                           command=lambda: self.clear_history(combo))
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def delete_history_item(self, combo, value):
        """删除指定的历史记录项"""
        current_values = list(combo['values'])
        if value in current_values:
            current_values.remove(value)
            combo['values'] = current_values
            self.log(f"已删除历史记录: {value}")

    def clear_history(self, combo):
        """清空所有历史记录"""
        combo['values'] = []
        self.log("已清空历史记录")

    # ===== 操作函数 =====

    def get_fields(self) -> List[str]:
        return [f.strip() for f in self.fields_var.get().split(',') if f.strip()]

    def do_extract(self):
        target = self.extract_dir_var.get()
        output = self.extract_output_var.get()
        if not target or not output:
            messagebox.showwarning("提示", "请填写目录和输出文件/目录")
            return
        
        filter_ftl = self.filter_ftl_var.get()
        by_folder = self.by_folder_var.get()
        fields = self.get_fields()
        
        if by_folder:
            # 按文件夹分组模式
            self.run_in_thread(extract_strings_by_folder, target, output, fields, 
                              filter_ftl,
                              success_msg="提取完成！")
        else:
            # 单文件模式
            self.run_in_thread(extract_strings, target, output, fields, 
                              False, filter_ftl,  # incremental=False, filter_ftl
                              success_msg="提取完成！")

    def do_test_connection(self):
        token = self.pz_token_var.get()
        pid = self.pz_project_id_var.get()
        if not token or not pid:
            messagebox.showwarning("提示", "请填写项目 ID 和 Token")
            return
        
        def _test():
            client = PZClient(int(pid), token)
            return client.test_connection()
        
        self.run_in_thread(_test, success_msg="连接测试成功！")

    def do_upload(self):
        token = self.pz_token_var.get()
        pid = self.pz_project_id_var.get()
        
        # 优先使用同步选项卡的上传路径，如果为空则回退到提取输出路径
        target = self.upload_path_var.get().strip() if hasattr(self, 'upload_path_var') else ""
        if not target:
            target = self.extract_output_var.get()
        
        if not token:
            messagebox.showwarning("提示", "请输入 Token")
            return
        if not target:
            messagebox.showwarning("提示", "请在「上传文件/目录」中指定要上传的路径")
            return
        if not os.path.exists(target):
            messagebox.showwarning("提示", f"指定的路径不存在: {target}")
            return
        
        def _upload():
            client = PZClient(int(pid), token)
            # 自动检测：如果是目录则批量上传，否则上传单文件
            if os.path.isdir(target):
                self.log(f"📂 检测到目录，使用批量上传模式: {target}")
                result = client.upload_folder(target)
                return result.get("uploaded", 0) > 0 or result.get("failed", 0) == 0
            else:
                self.log(f"📄 上传单文件: {target}")
                return client.upload_file(target)
        
        self.run_in_thread(_upload, success_msg="上传成功！")

    def do_download(self):
        token = self.pz_token_var.get()
        pid = self.pz_project_id_var.get()
        local_file = self.download_path_var.get()  # 使用新的下载路径变量
        if not token:
            messagebox.showwarning("提示", "请输入 Token")
            return
        if not local_file:
            messagebox.showwarning("提示", "请指定下载保存路径")
            return
        
        def _download():
            client = PZClient(int(pid), token)
            return client.download_file(local_file)
        
        self.run_in_thread(_download, success_msg=f"下载成功！已保存到: {local_file}")

    def do_merge(self):
        input_file = self.merge_input_var.get()
        target_dir = self.merge_source_var.get()
        if not os.path.exists(input_file):
            messagebox.showwarning("错误", f"找不到翻译文件：{input_file}")
            return
        self.run_in_thread(merge_translations, target_dir, input_file, target_dir, self.get_fields(),
                          success_msg="合并完成！")

    def do_full_workflow(self):
        """执行一键工作流"""
        token = self.pz_token_var.get()
        pid = self.pz_project_id_var.get()
        
        if not token:
            messagebox.showwarning("提示", "请先在「Paratranz 同步」选项卡中填写 API Token")
            self.notebook.select(self.tab_sync)
            return
        
        scan_dir = self.extract_dir_var.get()
        output_json = self.extract_output_var.get()
        translation_json = self.merge_input_var.get()
        output_dir = self.merge_source_var.get()
        fields = self.get_fields()
        
        # 读取分组模式选项
        by_folder = self.by_folder_var.get()
        filter_ftl = self.filter_ftl_var.get()
        
        self.run_in_thread(
            run_full_workflow,
            scan_dir, output_json, translation_json,
            int(pid), token, output_dir, fields,
            by_folder, filter_ftl,
            success_msg="一键工作流执行完成！"
        )

# ==================== 主程序入口 (Main) ====================

if __name__ == "__main__":
    setup_logging()
    # 如果没有命令行参数，启动 GUI
    if len(sys.argv) == 1:
        try:
            root = tk.Tk()
            app = App(root)
            root.mainloop()
        except Exception as e:
            with open("error_log.txt", "w") as f:
                import traceback
                f.write(traceback.format_exc())
    # 否则解析命令行参数
    else:
        parser = argparse.ArgumentParser(description="SS14 Localization Tracker CLI v3.0")
        subparsers = parser.add_subparsers(dest='command')
        
        # Extract 命令
        p_extract = subparsers.add_parser('extract', help='Extract strings')
        p_extract.add_argument('--source', help='Source repo root (Optional)')
        p_extract.add_argument('--target_folders', required=True, help='Target directory')
        p_extract.add_argument('--output', required=True, help='Output JSON file or directory (for --by-folder)')
        p_extract.add_argument('--fields', help='Comma-separated list of fields to extract')
        p_extract.add_argument('--incremental', action='store_true', 
                               help='Enable incremental mode (skip unchanged files)')
        p_extract.add_argument('--filter-ftl', action='store_true', default=True,
                               help='Filter out FTL localization keys (default: enabled)')
        p_extract.add_argument('--no-filter-ftl', action='store_true',
                               help='Disable FTL key filtering')
        p_extract.add_argument('--by-folder', action='store_true',
                               help='Generate multiple JSON files by folder structure')
        
        # Merge 命令
        p_merge = subparsers.add_parser('merge', help='Merge translations')
        p_merge.add_argument('--source', required=True, help='Source directory')
        p_merge.add_argument('--input', required=True, help='Input JSON file')
        p_merge.add_argument('--output', required=True, help='Output directory')
        p_merge.add_argument('--fields', help='Comma-separated list of fields to merge')
        
        # Upload 命令
        p_upload = subparsers.add_parser('upload', help='Upload to Paratranz')
        p_upload.add_argument('--file', help='Single file to upload')
        p_upload.add_argument('--folder', help='Folder of JSON files to upload (batch mode)')
        p_upload.add_argument('--project_id', type=int, default=os.environ.get('PZ_PROJECT_ID'))
        p_upload.add_argument('--token', default=os.environ.get('PARATRANZ_TOKEN'))
        
        # Upload-Translation 命令（上传译文）
        p_upload_trans = subparsers.add_parser('upload-translation', help='Upload translations to Paratranz')
        p_upload_trans.add_argument('--file', help='Single translation file to upload')
        p_upload_trans.add_argument('--folder', help='Folder of translation JSON files to upload (batch mode)')
        p_upload_trans.add_argument('--force', action='store_true', 
                                    help='Force overwrite translations that have been manually edited')
        p_upload_trans.add_argument('--project_id', type=int, default=os.environ.get('PZ_PROJECT_ID'))
        p_upload_trans.add_argument('--token', default=os.environ.get('PARATRANZ_TOKEN'))
        
        # Download 命令
        p_download = subparsers.add_parser('download', help='Download from Paratranz')
        p_download.add_argument('--file', required=True, help='File to save')
        p_download.add_argument('--remote', help='Remote filename match')
        p_download.add_argument('--project_id', type=int, default=os.environ.get('PZ_PROJECT_ID'))
        p_download.add_argument('--token', default=os.environ.get('PARATRANZ_TOKEN'))
        
        # Workflow 命令
        p_workflow = subparsers.add_parser('workflow', help='Run full workflow')
        p_workflow.add_argument('--scan_dir', required=True, help='Directory to scan')
        p_workflow.add_argument('--output_json', default='en.json', help='Extracted JSON file')
        p_workflow.add_argument('--translation_json', default='zh.json', help='Translation JSON file')
        p_workflow.add_argument('--output_dir', required=True, help='Output directory for merged files')
        p_workflow.add_argument('--project_id', type=int, default=os.environ.get('PZ_PROJECT_ID'))
        p_workflow.add_argument('--token', default=os.environ.get('PARATRANZ_TOKEN'))
        p_workflow.add_argument('--incremental', action='store_true', 
                               help='Enable incremental extraction mode')
        p_workflow.add_argument('--by-folder', action='store_true',
                               help='Generate multiple JSON files by folder structure')
        p_workflow.add_argument('--filter-ftl', action='store_true', default=True,
                               help='Filter out FTL localization keys (default: enabled)')
        p_workflow.add_argument('--no-filter-ftl', action='store_true',
                               help='Disable FTL key filtering')
        
        args = parser.parse_args()
        
        if args.command == 'extract':
            scan_path = args.target_folders
            if args.source:
                scan_path = os.path.join(args.source, args.target_folders)
            fields = args.fields.split(',') if args.fields else None
            filter_ftl = not args.no_filter_ftl  # 默认开启过滤
            
            if args.by_folder:
                # 按文件夹分组模式
                extract_strings_by_folder(scan_path, args.output, fields, 
                                          filter_ftl=filter_ftl)
            else:
                # 单文件模式
                extract_strings(scan_path, args.output, fields, 
                               incremental=args.incremental, filter_ftl=filter_ftl)
            
        elif args.command == 'merge':
            src_path = args.source
            if os.path.exists(os.path.join(src_path, 'Content')):
                src_path = os.path.join(src_path, 'Content')
            fields = args.fields.split(',') if args.fields else None
            merge_translations(src_path, args.input, args.output, fields)
            
        elif args.command == 'upload':
            client = PZClient(args.project_id, args.token)
            if args.folder:
                # 批量上传模式
                client.upload_folder(args.folder)
            elif args.file:
                client.upload_file(args.file)
            else:
                log("请指定 --file 或 --folder 参数", "ERROR")
        
        elif args.command == 'upload-translation':
            client = PZClient(args.project_id, args.token)
            if args.folder:
                # 批量上传译文模式
                client.upload_translation_folder(args.folder, force=args.force)
            elif args.file:
                client.upload_translation(args.file, force=args.force)
            else:
                log("请指定 --file 或 --folder 参数", "ERROR")
            
        elif args.command == 'download':
            client = PZClient(args.project_id, args.token)
            client.download_file(args.file, args.remote)
            
        elif args.command == 'workflow':
            filter_ftl = not args.no_filter_ftl
            run_full_workflow(
                args.scan_dir, args.output_json, args.translation_json,
                args.project_id, args.token, args.output_dir,
                fields=None,  # CLI模式使用默认字段
                by_folder=args.by_folder,
                filter_ftl=filter_ftl,
                incremental=args.incremental
            )

