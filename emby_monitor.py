#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 本脚本适合在群晖 NAS 上运行，单脚本可以使用计划任务直接运行，监控指定文件夹内的视频文件变动，
# 并通过 Emby API 通知 Emby 服务器扫描更新媒体库（支持单库和全局扫描）。 
# 适合用于 Docker 容器内运行的 Emby 服务器。
# 并且支持 NAS 路径到 Emby 容器内部路径的映射。 并且支持多媒体库监控。
# 适用于 Emby 服务器版本 4.x 及以上，远程SMB，WebDAV等不在一个主机上的不能直接使用Emby文件夹监控的情况。
# Powered by PeiFeng.Li - https://peifeng.li
# Version = "v1.0.0 - 2025-10-18"

import os
import time
import logging
import threading
from logging.handlers import RotatingFileHandler
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- 您需要在此处进行配置 ---
# Emby 服务器信息
EMBY_SERVER_URL = "http://10.0.0.88:8096"  # 替换为您的 Emby 服务器地址
EMBY_API_KEY = "888888888888888888"           # 替换为您的 Emby API 密钥

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
    "/volume1/Video/电影": "1",  # 电影
    "/volume1/Video/电视剧": "2",  # 电视剧
    # 在这里添加更多您需要监控的文件夹和对应的媒体库 ID...
}

# 要监控的视频文件扩展名（小写）
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.mpg', '.mpeg', '.flv', '.webm', '.ts', '.rmvb', '.iso', '.vob')

# 扫描触发周期（秒）
SCAN_INTERVAL_SECONDS = 300  # 每隔5分钟检查一次文件变动
# 日志文件配置
LOG_FILE_PATH = "/volume5/docker/scripts/emby_monitor.log"  # 日志文件存放路径，请确保该目录存在
LOG_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
LOG_BACKUP_COUNT = 2  # 最多保留3个日志文件 (monitor.log, monitor.log.1, monitor.log.2)

# --- 配置结束 ---


# 全局变量，用于在线程间共享待处理的扫描请求
scan_requests = set()
FULL_SCAN_MARKER = "full_scan"
log_lock = threading.Lock()

def setup_logging():
    """配置日志记录器"""
    logger = logging.getLogger("EmbyMonitor")
    logger.setLevel(logging.INFO)

    # 防止重复添加 handler
    if logger.hasHandlers():
        logger.handlers.clear()

    formatter = logging.Formatter('[%(asctime)s]  %(message)s', datefmt='%m-%d %H:%M:%S')

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

logger = setup_logging()

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
        endpoint_desc = f"媒体库扫描 (编号: {library_id})"
        
        # 使用映射表获取对应的NAS路径
        nas_paths = [path for path, lid in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.items() if lid == library_id]
        
        if not nas_paths:
            logger.error(f"🔴 找不到媒体库(编号: {library_id}) 对应的路径。请检查映射表配置。")
            return False
        
        # 获取第一个NAS路径对应的容器内部路径
        nas_path = nas_paths[0]
        container_path = NAS_TO_CONTAINER_PATH_MAP.get(nas_path)
        
        if not container_path:
            logger.error(f"🔴 找不到 {nas_path} 对应的容器内部路径。请检查 NAS_TO_CONTAINER_PATH_MAP 映射表。")
            return False
        
        json_data = {
            "Updates": [{
                "Path": container_path,
                "UpdateType": "scan"
            }]
        }
        
        try:
            logger.info(f"🟣 正在发送 Emby API 请求: {endpoint_desc}...")
            response = requests.post(url, headers=headers, json=json_data, timeout=30)
            
            if response.status_code == 204:
                logger.info(f"🟢 成功发送请求，Emby 已开始{endpoint_desc}")
                return True
            else:
                logger.error(f"🔴 发送 Emby API 请求失败 ({endpoint_desc})。状态码: {response.status_code}, 响应: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 连接 Emby 服务器时发生网络错误 ({endpoint_desc})。错误: {e}")
            return False
            
    else:
        url = f"{EMBY_SERVER_URL}/emby/Library/Refresh"
        endpoint_desc = "全部媒体库扫描"
        
        try:
            logger.info(f"🟣 正在发送 Emby API 请求: {endpoint_desc}...")
            response = requests.post(url, headers=headers, timeout=30)
            
            if response.status_code == 204:
                logger.info(f"🟢 成功发送请求: {endpoint_desc}。Emby 已开始扫描。")
                return True
            else:
                logger.error(f"🔴 发送请求失败 ({endpoint_desc})。状态码: {response.status_code}, 响应: {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"🔴 连接服务器时发生网络错误 ({endpoint_desc})。错误: {e}")
            return False

class VideoChangeHandler(FileSystemEventHandler):
    """文件系统事件处理器"""
    def _is_video_file(self, path):
        """检查文件是否为指定的视频格式"""
        return path.lower().endswith(VIDEO_EXTENSIONS)

    def _queue_scan_request(self, path):
        """根据文件路径，将对应的扫描请求加入队列"""
        if not self._is_video_file(path):
            return

        matched_library_id = None
        # 从最长的路径开始匹配，避免子目录匹配错误
        sorted_paths = sorted(MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys(), key=len, reverse=True)

        for folder_path in sorted_paths:
            if path.startswith(folder_path):
                matched_library_id = MONITORED_FOLDERS_TO_LIBRARY_ID_MAP[folder_path]
                break
        
        with log_lock:
            if matched_library_id:
                logger.info(f"🟠 检测到变动: {path}。扫描队列已加入媒体库编号: {matched_library_id}。")
                scan_requests.add(matched_library_id)
            else:
                logger.info(f"🟠 检测到变动: {path}。未匹配到媒体库编号，将触发全库扫描。")
                scan_requests.add(FULL_SCAN_MARKER)

    def on_created(self, event):
        if not event.is_directory:
            logger.info(f"🟠 文件创建: {event.src_path}")
            self._queue_scan_request(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            logger.info(f"🟠 文件删除（自定义不进行刷新扫描）: {event.src_path}")
           # self._queue_scan_request(event.src_path)
           # 如果需要变更扫描，取消上一行的注释

    def on_moved(self, event):
        if not event.is_directory:
            logger.info(f"🟠 文件移动/重命名: 从 {event.src_path} 到 {event.dest_path}")
            # 移动/重命名事件，源和目标路径都可能触发扫描
            self._queue_scan_request(event.src_path)
            self._queue_scan_request(event.dest_path)

def main():
    """主函数"""
    logger.info("="*50)
    logger.info("❤️ Emby 媒体库监测脚本已启动。")
    logger.info(f"❤️ 将每隔 {SCAN_INTERVAL_SECONDS} 秒检查一次文件变动。")
    logger.info("❤️ 正在监控以下文件夹:")
    for path in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys():
        logger.info(f"📂  {path}")

    event_handler = VideoChangeHandler()
    observer = Observer()

    for path in MONITORED_FOLDERS_TO_LIBRARY_ID_MAP.keys():
        if not os.path.isdir(path):
            logger.error(f"⚠️ 配置的路径不存在或不是一个目录: {path}。已跳过。")
            continue
        observer.schedule(event_handler, path, recursive=True)

    observer.start()
    logger.info("🟢 文件系统监测已启动...")

    try:
        while True:
            time.sleep(SCAN_INTERVAL_SECONDS)
            
            with log_lock:
                if not scan_requests:
                    logger.info("⚪️ 此周期内未监测到视频文件变动，所以将不会请求 Emby 扫描媒体库。")
                    continue

                logger.info(f"🟠 检测到文件变动，待处理的扫描媒体库编号请求 {list(scan_requests)}")

                # 优先级判断：如果全库扫描在请求中，则只执行全库扫描
                if FULL_SCAN_MARKER in scan_requests:
                    logger.info("🟣 检测到全部媒体库扫描请求，将优先执行全部媒体库扫描并忽略其他特定媒体库扫描。")
                    trigger_emby_scan()
                else:
                    logger.info("🟣 正在对发生变动的特定媒体库发送扫描请求...")
                    for library_id in list(scan_requests):
                        trigger_emby_scan(library_id)
                
                # 清空本次周期的请求
                scan_requests.clear()
                logger.info("🟢 扫描队列已操作完成并清空，等待下一个扫描周期。")

    except KeyboardInterrupt:
        logger.warning("🔴 接收到停止信号，正在关闭脚本...")
    finally:
        observer.stop()
        observer.join()
        logger.info("🔴 文件监测系统已停止。脚本已关闭。")

if __name__ == "__main__":
    main()