# 第三方组件

本仓库自有代码的 MIT 许可不覆盖第三方组件。

| 组件 | 用途 | 上游与许可 |
|---|---|---|
| Python / Tkinter | 运行环境与窗口 | Python Software Foundation / Tcl/Tk |
| Mido | MIDI 解析 | https://github.com/mido/mido ，MIT |
| Truststore | Windows 原生证书验证 | https://github.com/sethmlarson/truststore ，MIT |
| Packaging | Mido 的依赖 | https://github.com/pypa/packaging ，Apache-2.0 / BSD-2-Clause |
| PyInstaller | 可选打包 | https://github.com/pyinstaller/pyinstaller ，GPL-2.0-or-later，含程序分发例外 |
| Interception | 可选系统输入适配器 | https://github.com/oblitum/Interception ，按上游双许可条款 |

## Interception

上游 README 声明：非商业用途的库及其源码采用 LGPL；商业用途另有商业许可。库的 LGPL v3 文本保存在 `third_party/interception/LICENSE.txt`。不得将本项目的 MIT 理解为对 Interception 商业使用的授权。

- 官方项目：https://github.com/oblitum/Interception
- 官方 v1.0.1 发布资产：https://github.com/oblitum/Interception/releases/tag/v1.0.1
- 库源码：https://github.com/oblitum/Interception/tree/v1.0.1/library
- 上游许可说明：https://github.com/oblitum/Interception#license

仓库不再分发其 DLL、驱动、安装器或包含它们的 EXE。获取脚本由使用者主动运行，从官方发布下载 ZIP，按散列核对后只提取 DLL；不执行或安装下载文件。自行构建与再分发应遵循各组件上游许可。

固定来源记录：

- ZIP SHA-256：`ad038963d6413055765128b0b931f6e765147c9916dba79e65d872b261f9af10`
- x64 DLL SHA-256：`ab88164c11b1b48488772d4c3bfaa4509d5b0ae9dbc5a691dc4f96f0260443c8`

上游软件与本项目独立维护。本项目适配器只创建/销毁上下文、检查设备可用性、发送音键，不设置输入过滤器，不接收或记录物理键盘输入。
