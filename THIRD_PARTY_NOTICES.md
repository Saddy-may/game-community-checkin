# 第三方来源与许可

整理及修改日期：2026-11-03。原始整合与修改：Copyright (c) 2026 Saddy-may。

桌面框架、界面、本地加密、调度、账号保护和结果复核在本项目实现。适配器参考官方前端与以下社区项目，森空岛及塔吉多部分包含跨语言改写。独立运行不免除来源许可义务。本项目采用 GNU AGPL version 3；上游部分保留原许可，不擅自增加“or later”。

| 本地范围与关系 | 来源 | 许可与原声明 |
| --- | --- | --- |
| `skland.py`：授权、签名、签到流程参考/改写 | [ErikaCarnea/SklandCheckin](https://github.com/ErikaCarnea/SklandCheckin) | MIT；Copyright (c) 2025 HeathErika |
| `skland.py`：跨语言改写、终末地流程 | [FCAnon89/SklandAutoSign](https://github.com/FCAnon89/SklandAutoSign) | MIT；Copyright (c) 2026 FCAnon89 |
| `miyoushe.py`：DS、角色、国服签到参考 | [Womsxd/MihoyoBBSTools](https://github.com/Womsxd/MihoyoBBSTools) | MIT；Copyright (c) 2021-2022 Womsxd |
| `miyoushe.py`：签到行为核对 | [mxf133/mys-signin-helper](https://github.com/mxf133/mys-signin-helper) | MIT；Copyright (c) 2026 mxf133 |
| `kuro.py`：请求/响应协议参考 | [leeezep/kurobbs_auto_checkin](https://github.com/leeezep/kurobbs_auto_checkin) | MIT；Copyright (c) 2025 leeezep |
| `kuro.py`：角色/状态码/签到字段参考 | [mxyooR/Kuro-autosignin](https://github.com/mxyooR/Kuro-autosignin) | GPL version 3 |
| 登录方案可行性资料，未采用其短信登录代码 | [mxyooR/Kuro_login](https://github.com/mxyooR/Kuro_login) | MIT；Copyright (c) 2025 MX |
| `tajiduo.py`：SDK短信、签名、刷新及签到的 Python 改写 | [zzstar101/taygedo-auto-attendance](https://github.com/zzstar101/taygedo-auto-attendance) | MIT；Copyright (c) 2026 zzstar101 |
| `tajiduo.py`：协议与刷新语义核对 | [Candy-QAQ/NTE-Auto-Sign](https://github.com/Candy-QAQ/NTE-Auto-Sign) | MIT；Copyright (c) 2023 xxyz30（原始版权人，非仓库名） |
| `gf2.py`：社区签到、每日任务和兑换流程参考 | [Tsuk1ko/gf2-bbs-sign-in](https://github.com/Tsuk1ko/gf2-bbs-sign-in) | GNU AGPL version 3；未另附可确认的项目版权行，不把 FSF 的许可证文本版权当作程序版权 |

各份原文按“所有者-仓库.txt”保存在 `LICENSES/upstream/`。MIT 声明及免责条款原样保留。对 GPL/AGPL 参考关系采用保守的完整源码分发方式，并保留原 GPL 范围，遵守 GPLv3/AGPLv3 第13条的组合规则；没有把仅有协议参考的资料宣传为捆绑了其代码。

本项目改动：整合为 Python 模块，增加手动官方登录、本地加密、角色筛选、账号一致性、逐角色结果、提交后复核、兑换优先规则/上限及超时保护。上游没有为这些修改背书。

## gf2gacha 的范围

[MatchaCabin/gf2gacha v1.19.2](https://github.com/MatchaCabin/gf2gacha/tree/v1.19.2) 曾用于研究社区接口与会话复用，并提供可选配置兼容格式。检查完整版本目录与 README 后，未发现明确项目许可证，因此不复制、捆绑它的源码、可执行文件、图片或运行库，也不替它授予 AGPL。

当前适配器与其 Go 源码逐项对照，未发现可识别的代码表达、注释、提示文案或特有控制结构移植。共同 API 路径、字段及任务名已由官方前端独立核对。保留这段研究来源，不宣称获得了它的授权，也不宣称清洁室开发或完全自研。

当前社区端点及字段独立核对于官方前端：<https://community-cdn.exiliumgf.com/website/source/bbspc1792997299712/js/app.c9a59359.js>。签到、任务和兑换亦与 Tsuk1ko 的已授权实现核对。`auth.import_gf2_config` 仅按用户选择读取已有社区会话与兑换偏好，不读取游戏日志或执行 gf2gacha。真实用户配置不分发。

## 依赖、素材和对应源码

依赖、Python/Tcl/Tk、Playwright 内置驱动及构建工具的许可见 `DEPENDENCY_LICENSES.md` 与 `LICENSES/dependencies/`。PyInstaller 带有打包例外。

官方游戏图标属于各发行商，来源及校验值见 `assets/icons/SOURCES.json`，不在本项目 AGPL 授权范围内。源码导出不包含这些位图；可在本机按需获取。`tools/checkin.ico` 为本项目绘制的签到图形。

便携包 `source/` 提供本次对应源码、构建脚本、依赖要求及修改说明。修改后分发时须同步对应源码。仅提供“致谢”链接不能代替完整许可证和源码义务。
