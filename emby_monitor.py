#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Emby File Monitor with Telegram Bot
# Powered by PeiFeng.Li - https://peifeng.li
# 本脚本适合在群晖 NAS 上运行，单脚本可以使用计划任务直接运行，监控指定文件夹内的视频文件变动，
# 并通过 Emby API 通知 Emby 服务器扫描更新媒体库（支持单库和全局扫描）。 
# 支持通过Telegram 机器人通知变动情况。
# 适合用于 Docker 容器内运行的 Emby 服务器。
# 并且支持 NAS 路径到 Emby 容器内部路径的映射。 并且支持多媒体库监控。
# 适用于 Emby 服务器版本 4.x 及以上，远程SMB，WebDAV等不在一个主机上的不能直接使用Emby文件夹监控的情况。
# Version = "v1.1.0 - 2025-10-20"  # 更新版本号

import os
import time
import logging
import threading
from logging.handlers import RotatingFileHandler
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import sys
import fcntl
import traceback

# --- 您需要在此处进行配置 ---
# Emby 服务器信息
EMBY_SERVER_URL = "http://10.0.0.3:8096"  # 替换为您的 Emby 服务器地址
EMBY_API_KEY = "88888888888888888888"           # 替换为您的 Emby API 密钥

# Telegram Bot 配置
TELEGRAM_BOT_TOKEN = "88888888888888888"  # 替换为您的 Telegram Bot Token
TELEGRAM_CHAT_ID = "88888888"      # 替换为您的 Telegram Chat ID

# NAS路径到Emby容器内部路径的映射
# 格式: {"NAS上的绝对路径": "Emby容器内部看到的路径"}
NAS_TO_CONTAINER_PATH_MAP = {
    "/volume1/Video/电影": "/Nas1/Video/电影",
    "/volume1/Video/电视剧": "/Nas1/Video/电视剧",
    # 添加更多映射...
}

# 媒体库路径到 ID 的映射
# 格式: {"NAS 上的绝对路径": "Emby 媒体库 ID"}
MONITORED_FOLDERS_TO_LIBRARY_ID_MAP = {
    "/volume1/Video/电影": "88888",  # 电影
    "/volume1/Video/电视剧": "8888888",  # 电视剧
    # 在这里添加更多您需要监控的文件夹和对应的媒体库 ID...
}

# 媒体库ID到名称的映射
LIBRARY_ID_TO_NAME = {
    "888": "成人",
    "88888": "电影",
    "8888888": "电视剧",
    # 添加更多映射...
}

# 要监控的视频文件扩展名（小写）
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mpg', '.mpeg', '.flv', '.webm', '.ts', '.rmvb', '.iso', '.vob')

# 扫描触发周期（秒）
SCAN_INTERVAL_SECONDS = 600  # 每隔10分钟检查一次文件变动
# 日志文件配置
LOG_FILE_PATH = "/volume5/docker/EmbyFMB/EmbyFMB.log"  # 日志文件存放路径，请确保该目录存在
LOG_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
LOG_BACKUP_COUNT = 2  # 最多保留3个日志文件 (monitor.log, monitor.log.1, monitor.log.2)

# --- 配置结束 ---

# 单实例锁检查
def single_instance_lock(lockfile):
    try:
        lock_file = open(lockfile, 'w')
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except IOError:
        return False

# 全局变量，用于在线程间共享待处理的扫描请求
scan_requests = set()
file_changes = []  # 存储文件变动信息
FULL_SCAN_MARKER = "full_scan"
log_lock = threading.Lock()

def setup_logging():
    """配置日志记录器"""
    logger = logging.getLogger("EmbyFMB")
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s  %(message)s\n', datefmt='%m-%d %H:%M:%S')

    # 创建一个轮转文件处理器
    # maxBytes: 日志文件最大大小
    # backupCount: 保留的旧日志文件数量
    handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 同时输出到控制台，方便调试
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# 在全局范围内初始化日志
try:
    logger = setup_logging()
    logger.info("🟢 日志系统初始化成功")
except Exception as e:
    print(f"🔴 日志系统初始化失败: {str(e)}")
    sys.exit(1)

def send_telegram_notification(message):
    """通过Telegram Bot发送通知"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ TG BOT未配置，跳过通知发送")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info("🟢 Telegram通知发送成功")
            return True
        else:
            logger.error(f"🔴 Telegram通知发送失败，状态码: {response.status_code}")
            logger.error(f"🔴 响应内容: {response.text}")
            return False
    except Exception as e:
        logger.error(f"🔴 发送Telegram通知时出错: {str(e)}")
        return False

def trigger_emby_scan(library_id=None):
    """
    向 Emby API 发送媒体库扫描请求
    :param library_id: 要扫描的媒体库编号。如果为空，则触发全库扫描。
    """
    headers = {
        'X-Emby-Token': EMBY_API_KEY,
        'Content-Type': 'application/json',
    }
    
    if library_id:
        url = f"{EMBY_SERVER_URL}/emby/Library/Media/Updated"
        
        # 获取媒体库名称
        library_name = LIBRARY_ID_TO_NAME.get(library_id, f"未知({library_id})")
        endpoint_desc = f"{library_name}媒体库扫描"
        
        # 使用映射表获取对应的NAS路径
        nas_paths = [path for path, lid in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.items() if lid == library_id]
        
        if not nas_paths:
            logger.error(f"🔴 找不到媒体库{library_name}对应的路径")
            logger.error("🔴 请检查配置部分映射表内容")
            return False
        
        # 获取第一个NAS路径对应的容器内部路径
        nas_path = nas_paths[0]
        container_path = NAS_TO_CONTAINER_PATH_MAP.get(nas_path)
        
        if not container_path:
            logger.error(f"🔴 找不到 {nas_path} 对应的容器内部路径")
            logger.error("🔴 请检查配置部分映射表内容")
            return False
        
        json_data = {
            "Updates": [{
                "Path": container_path,
                "UpdateType": "scan"
            }]
        }
        
        try:
            logger.info("🟣 正在发送 Emby API 请求")
            logger.info(f"🟣 请求内容: {endpoint_desc}")
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
            
            if response.status_code == 204:
                logger.info("🟢 成功发送请求")
                logger.info(f"🟢 Emby 已开始{endpoint_desc}")
                return True
            else:
                logger.error(f"🔴 发送请求失败，状态码: {response.status_code}, 响应: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 连接服务器时发生网络错误: {e}")
            return False
            
    else:
        url = f"{EMBY_SERVER_URL}/emby/Library/Refresh"
        endpoint_desc = "全部媒体库扫描"
        
        try:
            logger.info("🟣 正在发送 Emby API 请求")
            logger.info(f"🟣 请求内容: {endpoint_desc}")
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 204:
                logger.info("🟢 成功发送请求")
                logger.info(f"🟢 Emby 已开始扫描全部媒体库")
                return True
            else:
                logger.error(f"🔴 发送请求失败，状态码: {response.status_code}, 响应: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 连接服务器时发生网络错误: {e}")
            return False

class VideoChangeHandler(FileSystemEventHandler):
    """文件系统事件处理器"""
    def _is_video_file(self, path):
        """检查文件是否为指定的视频格式"""
        return path.lower().endswith(VIDEO_EXTENSIONS)

    def _queue_scan_request(self, path, event_type):
        """根据文件路径，将对应的扫描请求加入队列，并记录变动信息"""
        if not self._is_video_file(path):
            logger.info("⚪️ 检测到非视频文件变动，忽略处理")
            logger.info(f"⚪️ 路径: {path}")
            return

        matched_library_id = None
        # 从最长的路径开始匹配，避免子目录匹配错误
        sorted_paths = sorted(MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys(), key=len, reverse=True)

        for folder_path in sorted_paths:
            if path.startswith(folder_path):
                matched_library_id = MONITORED_FOLDERS_TO_LIBRARY_ID_MAP[folder_path]
                break
        
        with log_lock:
            # 记录文件变动信息
            file_changes.append({
                "path": path,
                "event_type": event_type,
                "library_id": matched_library_id or "未知"
            })
            
            if matched_library_id:
                # 获取媒体库名称
                library_name = LIBRARY_ID_TO_NAME.get(matched_library_id, f"未知({matched_library_id})")
                logger.info("🟠 检测到有文件变动")
                logger.info(f"🟠 路径: {path}")
                logger.info(f"🟠 {library_name}媒体库已加入到待扫描队列")
                scan_requests.add(matched_library_id)
            else:
                logger.info("🟠 检测到有文件变动")
                logger.info(f"🟠 路径: {path}")
                logger.info("🟠 未匹配到媒体库编号，将全库扫描")
                scan_requests.add(FULL_SCAN_MARKER)

    def on_created(self, event):
        if not event.is_directory:
            logger.info("🟠 检测到有文件创建")
            logger.info(f"🟠 路径: {event.src_path}")
            self._queue_scan_request(event.src_path, "创建")

    def on_deleted(self, event):
        if not event.is_directory:
            logger.info("⚪️ 检测到有文件删除")
            logger.info(f"⚪️ 路径: {event.src_path}")
            logger.info("⚪️ 当前设置为不刷新或非视频文件")
            # 记录删除事件但不触发扫描
            with log_lock:
                file_changes.append({
                    "path": event.src_path,
                    "event_type": "删除",
                    "library_id": "不扫描"
                })

    def on_moved(self, event):
        if not event.is_directory:
            logger.info("🟠 检测到有文件移动/重命名")
            logger.info(f"🟠 从 {event.src_path}")
            logger.info(f"🟠 到 {event.dest_path}")
            # 移动/重命名事件，源和目标路径都可能触发扫描
            self._queue_scan_request(event.src_path, "移动(源)")
            self._queue_scan_request(event.dest_path, "移动(目标)")

# 在 main() 前调用
LOCK_FILE = "/tmp/EmbyFMB.lock"
if not single_instance_lock(LOCK_FILE):
    logger.error("🔴 另一个实例正在运行，退出")
    sys.exit(1)

def main():
    """主函数"""
    try:
        logger.info("🔸🔸🔸🔸🔸EmbyFMB🔸🔸🔸🔸🔸")
        logger.info("⚠️ 正在启动EmbyFMB监测系统")
        logger.info(f"⚠️ 当前设置 {SCAN_INTERVAL_SECONDS} 秒为一循环周期。")
        logger.info("⚠️ 非视频文件变动将被忽略并记录")
        logger.info("⚠️ 视频文件变动会发送TG BOT通知")
        logger.info("⚠️ 正在监控以下文件夹:")
        for path in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys():
            # 获取媒体库名称
            library_id = MONITORED_FOLDERS_TO_LIBRARY_ID_MAP[path]
            library_name = LIBRARY_ID_TO_NAME.get(library_id, f"未知({library_id})")
            logger.info(f"📂 - {path} ({library_name})")

        event_handler = VideoChangeHandler()
        observer = Observer()

        for path in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys():
            if not os.path.isdir(path):
                logger.error("⚠️ 配置的路径不存在或不是目录")
                logger.error(f"⚠️ 路径: {path}")
                continue
            observer.schedule(event_handler, path, recursive=True)

        logger.info("🔸🔸🔸🔸🔸详细日志🔸🔸🔸🔸🔸")
        observer.start()
        logger.info("🟢 服务已启动，正在监听指定文件夹")
        
        try:
            while True:
                time.sleep(SCAN_INTERVAL_SECONDS)
                
                with log_lock:
                    if not scan_requests and not file_changes:
                        logger.info("⚪️ 此周期内未监测到视频文件变动。")
                        continue

                    # 只有当有文件变动时才发送Telegram通知
                    if file_changes:
                        # 生成精美的Telegram通知消息
                        # 添加页头      
                        message = "⭐️EmbyFMB监测报告⭐️\n\n"
                        message += f"🕒 监测周期: {SCAN_INTERVAL_SECONDS}秒\n"
                        message += f"🔖 变动数量: {len(file_changes)}\n"
                        message += "—————————\n"
                        
                        # 按事件类型分类
                        event_types = {
                            "创建": {"icon": "🟢", "items": []},
                            "删除": {"icon": "🔴", "items": []},
                            "移动(源)": {"icon": "🟡", "items": []},
                            "移动(目标)": {"icon": "🔵", "items": []}
                        }
                        
                        for change in file_changes:
                            # 获取文件名（不含路径）
                            filename = os.path.basename(change['path'])
                            # 获取媒体库名称
                            library_name = LIBRARY_ID_TO_NAME.get(change['library_id'], f"未知({change['library_id']})")
                            
                            # 添加到对应事件类型的列表
                            if change['event_type'] in event_types:
                                event_types[change['event_type']]["items"].append({
                                    "filename": filename,
                                    "library": library_name
                                })
                        
                        # 添加变动详情
                        for event_type, data in event_types.items():
                            if data["items"]:
                                # 修复f-string括号问题
                                items_count = len(data["items"])
                                message += f"{data['icon']} {event_type} ({items_count})\n"
                                
                                for item in data["items"]:
                                    # 缩短过长的文件名（超过50字符）
                                    display_name = item['filename'] if len(item['filename']) <= 50 else item['filename'][:47] + "..."
                                    message += f"🍬 <code>{display_name}</code>\n"
                                    message += f"└ 🎞️ 媒体库: {item['library']}\n"
                                message += "—————————\n"
                        
                        # 添加扫描操作信息
                        message += "🎬 Emby服务器操作记录:\n"
                        if FULL_SCAN_MARKER in scan_requests:
                            message += "🟢 已触发全库扫描\n"
                        elif scan_requests:
                            for library_id in scan_requests:
                                library_name = LIBRARY_ID_TO_NAME.get(library_id, f"未知({library_id})")
                                message += f"🟢 已扫描刷新媒体库: {library_name}\n"
                        else:
                            message += "⚪️ 未触发刷新扫描（仅记录变动）\n"
                        
                        # 添加页脚
                        message += "\n©️Emby File Monitor with TG BOT"
                        
                        # 发送Telegram通知
                        send_telegram_notification(message)
                    else:
                        logger.info("⚪️ 没有文件变动，不发送TG通知。")
                    
                    # 处理扫描请求
                    if scan_requests:
                        # 获取媒体库名称列表
                        lib_names = []
                        for lib_id in scan_requests:
                            if lib_id == FULL_SCAN_MARKER:
                                lib_names.append("全库扫描")
                            else:
                                lib_name = LIBRARY_ID_TO_NAME.get(lib_id, f"未知({lib_id})")
                                lib_names.append(lib_name)
                        
                        logger.info("🟠 检测到有文件变动")
                        logger.info(f"🟠 待扫描处理媒体库: {', '.join(lib_names)}")

                        # 优先级判断：如果全库扫描在请求中，则只执行全库扫描
                        if FULL_SCAN_MARKER in scan_requests:
                            logger.info("🟣 检测到全部媒体库扫描请求")
                            logger.info("🟣 将优先执行并忽略其他扫描。")
                            trigger_emby_scan()
                        else:
                            logger.info("🟣 正在对特定媒体库发送扫描请求...")
                            for library_id in list(scan_requests):
                                trigger_emby_scan(library_id)
                    
                    # 清空本次周期的请求和变动记录
                    scan_requests.clear()
                    file_changes.clear()
                    logger.info("🟢 扫描队列和变动记录已清空")
                    logger.info("🟢 继续进行下一个扫描周期...")

        except KeyboardInterrupt:
            logger.warning("🔴 接收到停止信号，正在关闭脚本...")
        except Exception as e:
            logger.error(f"🔴 发生未处理的异常: {str(e)}")
            logger.error("🔴 异常堆栈:")
            logger.error(traceback.format_exc())
            logger.error("🔴 脚本将退出")
        finally:
            observer.stop()
            observer.join()
            logger.info("🔴 文件监测系统已停止。脚本已关闭。")
    
    except Exception as e:
        logger.error(f"🔴 主函数初始化失败: {str(e)}")
        logger.error("🔴 异常堆栈:")
        logger.error(traceback.format_exc())
        logger.error("🔴 脚本将退出")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 如果日志系统尚未初始化，尝试直接写入文件
        try:
            logger.error(f"🔴 脚本入口发生未处理的异常: {str(e)}")
            logger.error("🔴 异常堆栈:")
            logger.error(traceback.format_exc())
        except:
            with open("/tmp/EmbyFMB.log", "a") as f:
                f.write(f"Error: {str(e)}\n")
                f.write(traceback.format_exc())
        sys.exit(1)
