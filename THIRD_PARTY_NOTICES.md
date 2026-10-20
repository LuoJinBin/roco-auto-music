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

Git 源码不存放 DLL、驱动或安装器。Release 程序包包含固定版本的动态链接 DLL、许可文本、对应库源码及本项目构建说明；Release 同时单独提供对应上游源码 ZIP。程序包不包含或自动安装系统键鼠驱动。

源码构建时，获取脚本由使用者主动运行，从官方发布下载 ZIP，按散列核对后只提取 DLL；不执行或安装下载文件。修改或替换库版本后，可调整开源适配器中的版本校验并重新构建应用。自行构建与再分发应遵循各组件上游许可。

本次对应的上游源码提交为 `513556e660893ca294b2e287143abb40a9170bb3`（v1.0.1）。源码归档 SHA-256：`9306fa995e1240839acc226e279a38fec9a94dac99268e8b366d5dfd85f5728c`。应用源码与构建脚本随本项目公开，库源码随程序包及 Release 提供；本项目 MIT 许可不替代第三方许可。

固定来源记录：

- ZIP SHA-256：`ad038963d6413055765128b0b931f6e765147c9916dba79e65d872b261f9af10`
- x64 DLL SHA-256：`ab88164c11b1b48488772d4c3bfaa4509d5b0ae9dbc5a691dc4f96f0260443c8`

上游软件与本项目独立维护。本项目适配器只创建/销毁上下文、检查设备可用性、发送音键，不设置输入过滤器，不接收或记录物理键盘输入。
