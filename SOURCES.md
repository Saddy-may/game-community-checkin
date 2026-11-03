# 接口来源与实现边界

本工具的本地框架、界面和调度在本项目实现；适配器参考或改写了以下项目和官方前端。运行时不启动其他签到工具，也未包含其二进制。完整许可、改写关系与修改说明见 `THIRD_PARTY_NOTICES.md`，原许可全文见 `LICENSES/`。

- 森空岛： https://github.com/ErikaCarnea/SklandCheckin 、 https://github.com/FCAnon89/SklandAutoSign
- 米游社国服星铁： https://github.com/Womsxd/MihoyoBBSTools 、 https://github.com/mxf133/mys-signin-helper
- 库街区鸣潮： https://github.com/leeezep/kurobbs_auto_checkin 、 https://github.com/mxyooR/Kuro-autosignin 、 https://github.com/mxyooR/Kuro_login
- 塔吉多异环： https://github.com/zzstar101/taygedo-auto-attendance 、 https://github.com/Candy-QAQ/NTE-Auto-Sign
- 少前2官方社区： https://gf2-bbs.exiliumgf.com/ 、 https://github.com/MatchaCabin/gf2gacha/tree/v1.19.2 、 https://github.com/Tsuk1ko/gf2-bbs-sign-in

平台升级可能要求调整适配器。

gf2gacha 未发现明确项目许可证；不包含其程序或源文件。保留早期接口研究与配置兼容来源；当前社区端点/字段已通过官方前端独立核对，并与已授权的 Tsuk1ko 实现核对。不宣称完全自研或清洁室开发。

塔吉多当前PC社区通过 `/usercenter/wapi/login` 的OAuth Cookie会话登录；异环签到H5使用App bridge提供的 `HT_USER_ACCESS_TOKEN`，与普通网站Cookie会话不同。工具默认采用用户主动操作的官方SDK短信登录，取得并加密保存可续期的签到授权，不将网页头像登录误记为游戏签到已就绪。
