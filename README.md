# 每日签到 · 游戏社区助手

在 Windows 上统一处理游戏社区签到，支持一键执行、北京时间每天 **00:00:10** 自动执行，以及关闭窗口后的 Windows 后台执行。每款游戏可单独启用、隐藏，适配器可继续扩展。

| 游戏 | 当前功能 |
| --- | --- |
| 明日方舟、明日方舟：终末地 | 森空岛签到，共用一次登录，逐个处理角色 |
| 崩坏：星穹铁道（国服） | 米游社游戏签到 |
| 鸣潮（国服） | 库街区游戏签到，逐个处理绑定角色 |
| 异环 | 塔吉多游戏签到，助手内官方 SDK 短信登录 |
| 少女前线2：追放 | 官方社区签到、每日浏览/点赞/分享、社区积分兑换 |

## 使用与迁移

1. 从 [Releases](https://github.com/Saddy-may/game-community-checkin/releases/latest) 下载 Windows x64 ZIP，解压到可写入的文件夹，保留完整目录，双击 `签到助手.exe`。需要安装 Edge 或 Chrome，手动登录官方页面。
2. 点击“账号登录”，自行完成登录并“检查登录”。异环直接使用助手内短信登录。
3. 点击“一键签到”。两个自动执行开关默认关闭，在“自动签到与设置”中自行开启。

后台执行需电脑开机、联网、当前 Windows 用户已登录。

少前2独立运行。已有社区登录可选择导入一次，也可直接使用官方社区网页登录。兑换仅使用社区积分，受积分、库存及周期限额约束。

换电脑时复制干净 ZIP 并解压，重新登录各平台，再开启所需自动执行开关。移动程序目录后，应重新开启后台执行。EXE 必须连同 `_runtime`、`adapters` 等目录一起移动。


## 源码与构建

建议 Windows 10/11 x64、Python 3.13：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python app.py
```

离线测试、构建桌面目录、生成干净发布包：

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -q
.\.venv\Scripts\python tools/build_release.py
.\.venv\Scripts\python tools/package_release.py
```

桌面目录在 `build_release/签到助手/`，ZIP 在 `artifacts/`，包内 `source/` 附对应源码。GitHub 的 **Actions → Windows build → Run workflow** 可构建 Windows 包；完成后在该次运行的 **Artifacts** 下载。工作流不自动创建公开 Release，远端构建结果以 Actions 记录为准。

## 来源与许可

框架、界面、加密、调度及整合在本项目实现；平台适配器参考、改写了公开社区实现。运行时直接访问官方平台，不启动其他签到工具。

整合代码采用 **GNU AGPL version 3**，上游各自的 MIT、GPLv3 与 AGPLv3 声明完整保留。分发修改版或二进制时须提供对应源码、许可和修改说明。见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、[LICENSE](LICENSE)、[LICENSES/](LICENSES/)。

gf2gacha 未发现明确项目许可证，因此本项目不包含、重新授权其程序或源码；配置兼容与早期协议核对关系单独记录。游戏名称、图标及平台服务不由本项目授权，本工具也不是官方客户端。

操作说明：[使用说明.md](使用说明.md)；扩展：[plugins/README.md](plugins/README.md)；验证范围：[VALIDATION.md](VALIDATION.md)。

