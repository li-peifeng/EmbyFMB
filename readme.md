<p align="center">
  <a href="https://peifeng.li"><img width="184px" alt="logo" src="https://raw.githubusercontent.com/li-peifeng/li-peifeng.github.io/refs/heads/main/logo.png" />
  </a>
</p>

# 功能亮点
1. 高效监测：
- 使用 watchdog 库，实时监测文件系统事件（创建、删除、移动、重命名），比定时轮询扫描磁盘效率更高，资源占用更低。
3. 智能扫描：
- 只有在监测到视频文件发生变化时，才会在一个周期结束后触发扫描（可自定义时长）。
- 能够将变动的文件路径精确映射到 Emby 的媒体库ID，实现只扫描有变动的媒体库。
- 如果文件路径没有映射，则触发全库扫描。
- 智能优先级处理：如果在同一个周期内，既有需要单独扫描的库，又有需要全库扫描的请求，脚本会自动忽略所有单独扫描，只执行一次全盘扫描，避免冗余操作。
3. 专业日志系统：
- 集成 Python 的 logging 模块，输出详细的事件和操作日志。
- 自动日志轮转：日志文件大小严格控制在 1MB，最多保留 3 个日志文件。当 monitor.log 写满后，最早的日志文件会被自动删除。
4. 配置简单：
- 所有需要您修改的参数都集中在脚本的开头部分，一目了然。
5. 后台运行：
- 提供了在群晖中通过“任务计划程序”或 SSH 在后台稳定运行的说明。
6. Telegram bot 即时通知
- 支持通过Telegram 机器人通知文件变动情况。
- 可自定义通知延迟时间和emby请求时间

截图：

<img width="688" height="384" alt="截屏2025-10-19 17 01 45" src="https://github.com/user-attachments/assets/2a358502-8cac-42e4-a802-f505c34c73d1" />

<img width="792" height="421" alt="截屏2025-10-19 17 02 31" src="https://github.com/user-attachments/assets/24559889-c626-4a4c-900f-748b95efd4bd" />

![IMG_2287](https://github.com/user-attachments/assets/c8affb2b-bccd-4206-b58d-f56b32ca618e)


## 第1步：准备环境
在群晖上运行此脚本，需要先通过 SSH 登录到您的 NAS，并安装必要的 Python 库。
1. 开启群晖 SSH服务：
- 进入 DSM>控制面板＞终端机和 SNMP。
- 勾选“启动 SSH 功能”，端口默认为 22。
2. 使用 SSH 客户端登录：
- 使用如 PuTTY （Windows） 或终端 （macOS/Linux） 连接到您的 NAS。
- 使用您的管理员账户和密码登录。
3. 安装 Python 包：
- 群晖 DSM 7.x 及以上版本通常自带 Python 3。
- 运行以下命令安装 watchdog 和 requests 库。请使用 sudo -i 切换到 root 用户以确保权限足够，
- - 输入您的管理员密码
```
sudo -i
```
- - 为 Python 3 安装 pip (如果尚未安装)
```
python3 -m ensurepip
```
- - 安装必要的库
```
python3 -m pip install watchdog requests
```
## 第2步：获取 Emby API 密钥和媒体库 ID
1. 获取 API 密钥：
- 登录 Emby 网页端。
- 点击右上角的齿轮图标进入“管理”。
- 在左侧菜单中选择“API 密钥”。
- 点击“+ 新 API 密钥”按钮，给它一个描述性的名字（例如 nas_monitor_script），然后点击“确定”。
- 复制生成的 API 密钥字符串。
2. 获取媒体库 ID (可选，但推荐)：
- 在 Emby 管理后台，进入“媒体库”。
- 点击您想进行单独扫描的媒体库（例如“电影”）。
- 查看浏览器地址栏中的 URL。URL 的末尾会有一个 id=... 的部分。这个 id 就是该媒体库的 ID。
- 记下每个媒体库对应的文件夹路径和它的 ID。

## 第3步：创建并配置脚本
在您的群晖上，选择一个合适的位置（例如，在 docker 共享文件夹下创建一个 scripts 子文件夹），然后下载此仓库里的 emby_monitor.py，保存到文件夹下。

## 第4步：运行脚本
您有两种推荐的方式在群晖上长期运行此脚本。
### 方式一：使用“任务计划程序”（推荐，开机自启）
1. 打开 DSM > 控制面板 > 任务计划程序。
2. 点击“新增” > “触发的任务” > “用户定义的脚本”。
3. 常规 选项卡：
- 任务名称：Emby Monitor Script
- 用户账号：root (为了有足够的权限读取文件和运行脚本)
- 事件：选择“开机”。
4. 任务设置 选项卡：
- 在“用户定义的脚本”框中，输入以下命令。请确保将 /path/to/your/script/emby_monitor.py 替换为您脚本的真实路径。
5. 点击“确定”保存任务。
6. 创建完成后，可以右键点击该任务并选择“运行”来立即启动它，无需等待下次开机。
### 方式二：使用 SSH 手动运行
这种方式适合临时测试，当您关闭 SSH 连接后，脚本进程可能会被终止。
1. 通过 SSH 登录到您的 NAS。
2. 进入脚本目录：
```
cd /volume1/docker/scripts/
```
3. 运行脚本
```
python3 emby_monitor.py
```
4. 要让它在后台运行（即使关闭 SSH 窗口），请使用 nohup：
```
nohup python3 emby_monitor.py &
```
这会在当前目录创建一个 nohup.out 文件来记录标准输出。

## 如何检查脚本运行状况
- 查看日志文件：您可以直接在群晖的 File Station 中打开您在配置中指定的 LOG_FILE_PATH（例如 /volume1/docker/scripts/emby_monitor.log）来查看脚本的详细运行日志，包括文件变动检测、API 请求发送情况等。
- 查看进程：通过 SSH 登录后，可以运行 ps | grep emby_monitor.py 来检查脚本进程是否正在运行。
注意事项
- 路径正确性：请务必确保 MONITORED_FOLDERS_TO_LIBRARY_ID_MAP 中的路径是 NAS 上的绝对路径（通常以 /volumeX/ 开头）。
- 权限问题：使用 root 用户运行脚本可以最大程度避免文件读取权限问题。如果您使用其他用户，请确保该用户对所有监控的文件夹有读取权限。
- 首次运行：脚本启动后会立即开始监控，但在第一个5分钟周期结束前不会发送任何扫描请求。

# 注：
- 本脚本适合在群晖 NAS 上运行，单脚本可以使用计划任务直接运行，
- 监控指定文件夹内的视频文件变动，并通过 Emby API 通知 Emby 服务器扫描更新媒体库（支持单库和全局扫描）。 
- 适用于 Docker 容器内运行的 Emby 服务器。并且支持 NAS 路径到 Emby 容器内部路径的映射。 并且支持多媒体库监控。
- 适用于 Emby 服务器版本 4.x 及以上，远程SMB，WebDAV等不在一个主机上的不能直接使用inotify来进行Emby文件夹监控的情况。
