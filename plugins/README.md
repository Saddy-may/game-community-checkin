# 游戏模块扩展

将可信的 Python 模块放在此目录，或从主界面的“管理游戏”导入模块文件。
每个模块导出 `MODULES = [YourModule()]`，使用 `checkin_core.RunContext` 与 `RunResult`。
模块需提供 `id`、`name`、`platform`、`site`，以及 `run(ctx)`；推荐提供只读的 `validate(ctx)`。

`ctx.credential` 是该平台的本地解密凭据，`ctx.options` 是该游戏的设置；
`ctx.save_credential(new_dict)` 保存续期凭据，`ctx.log(message)` 写入脱敏日志。
失效登录抛出 `NeedLoginError`。成功状态必须经过真实接口核实。
不要记录登录凭据，不要将其发送到官方接口以外的服务。

同一平台的多个游戏可以共享 `platform`，各游戏的开启、显示、选项和当天状态独立。
删除界面中的游戏会停用并隐藏该项；其余游戏继续工作。插件文件按需手动移除。
