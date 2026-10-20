# Windows 安装与首次使用

## 选择下载

- 安装包：运行 Release 中的 `RocoAutoMusic-Setup-…-x64.exe`，选择目录与是否创建桌面快捷方式；可在 Windows 应用列表卸载。
- 免安装：解压 `RocoAutoMusic-…-Windows-x64.zip`，运行里面的 `RocoAutoMusic.exe`。

两种都自带 Python 运行环境。程序启动会由 Windows 请求管理员确认，以匹配可能以管理员权限运行的游戏。安装程序本身按用户安装，不会自动启动程序、播放曲谱、安装系统驱动或重启。

当前为未完成运行验收的预发布包；安装/卸载未进行实机测试。文件校验值见 Release 的 SHA256SUMS.txt。

## 首次配置输入

检测到已安装 Interception 时，工具默认选择它。系统驱动与程序目录中的 DLL 是两部分；程序包自带库，不代表已经安装了系统驱动。

已经配置过官方驱动的电脑无需重复安装。需要首次配置时，由使用者自行完成：

1. 从 [Interception 官方 v1.0.1 Release](https://github.com/oblitum/Interception/releases/tag/v1.0.1) 下载官方 ZIP；不要使用来源不明的驱动。
2. 解压并找到 `command line installer/install-interception.exe`。自行决定安装后，在该目录的管理员终端运行 `./install-interception.exe /install`。
3. 保存其他工作，由使用者主动正常重启，再进入游戏的九键演奏界面。

本项目不自动执行上述操作，不关闭系统安全功能。系统不允许驱动加载时，不通过修改安全设置强行加载。第三方许可见 THIRD_PARTY_NOTICES.md。

## 开始演奏

在工具中选曲，确认游戏窗口并勾选演奏界面确认，按 F8 开始。首次倒计时 3 秒；F8 暂停/继续，F9 停止复位。切换窗口会暂停，每首结束后停止，不自动下一首。

## 卸载

安装版使用 Windows 应用列表或程序目录中的卸载入口。卸载仅移除程序安装文件，不删除 `%LOCALAPPDATA%/RocoAutoMusic` 内的个人缓存和日志，也不卸载独立安装的第三方系统驱动。免安装版停止并退出后，可自行移除解压目录。
