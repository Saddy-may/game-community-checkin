# Python 与桌面运行时的第三方许可

本文件随便携版分发。许可原文集中在 [`LICENSES/dependencies/`](LICENSES/dependencies/)，各文件的来源与 SHA-256 记录在 [`MANIFEST.json`](LICENSES/dependencies/MANIFEST.json)。本清单核对日期为 2026-11-03，覆盖这次 Windows x64 构建可能携带的 Python 库、原生运行时、Playwright 驱动及其内嵌组件，不替代各组件的完整许可证。

本应用自己的许可不改变下列组件的许可。收集过程只复制发行包中的许可、NOTICE、版权文本和公开依赖清单，没有复制账号目录、登录信息、浏览器缓存或研究用网页源码。

## 版本依据与收集范围

- `vendor/` 中的库使用其实际安装的 `*.dist-info/METADATA` 与许可证，而不是 `requirements.txt` 的版本下限。
- requests、certifi、charset-normalizer、idna、urllib3、cryptography、cffi 来自构建所用 Python 安装的 `dist-info`，其版本与 PyInstaller 的 `Analysis-00.toc` 中实际来源一致。
- 构建分析中实际带入的 setuptools 内置库也列在下表。未带入的测试、文档和其他构建工具依赖不在本次分发清单中。
- PyInstaller 只因其启动器、加载模块和运行时钩子会进入最终程序而列入；未把它的全部构建工具依赖当作应用运行依赖。
- 本版本不包含 NumPy/threadpoolctl。本清单不包含它们的许可证；如果引入这些组件，需要补齐相应许可。

## Python 库

下表链接指向随本程序保存的原文。文件按原始字节复制，未把完整许可证改写为摘要。

| 组件 | 实际版本 | 许可与本地原文 |
| --- | --- | --- |
| requests | 2.32.5 | [Apache-2.0](LICENSES/dependencies/requests-2.32.5/licenses/LICENSE) |
| certifi | 2026.1.4 | [Mozilla CA 证书包许可声明](LICENSES/dependencies/certifi-2026.1.4/licenses/LICENSE)、[MPL-2.0 全文](LICENSES/dependencies/certifi-2026.1.4/MPL-2.0.txt) |
| charset-normalizer | 3.4.4 | [MIT](LICENSES/dependencies/charset-normalizer-3.4.4/licenses/LICENSE) |
| idna | 3.11 | [BSD-3-Clause](LICENSES/dependencies/idna-3.11/licenses/LICENSE.md) |
| urllib3 | 2.6.3 | [MIT](LICENSES/dependencies/urllib3-2.6.3/licenses/LICENSE.txt) |
| cryptography | 48.0.0 | [Apache-2.0 或 BSD-3-Clause](LICENSES/dependencies/cryptography-48.0.0/licenses/LICENSE)；两份完整许可同时保留 |
| cffi 后端 | 2.0.0 | [实际随包的 MIT No Attribution 文本](LICENSES/dependencies/cffi-2.0.0/licenses/LICENSE)，并保留 AUTHORS |
| CustomTkinter | 5.2.2 | [MIT，Copyright (c) 2023 Tom Schimansky](LICENSES/dependencies/customtkinter-5.2.2/LICENSE) |
| darkdetect | 0.8.0 | [BSD-3-Clause](LICENSES/dependencies/darkdetect-0.8.0/LICENSE) |
| packaging | 26.3 | [Apache-2.0 或 BSD-2-Clause](LICENSES/dependencies/packaging-26.3/licenses/LICENSE)；两份完整许可同时保留 |
| Pillow | 12.3.0 | [MIT-CMU 及 wheel 内嵌图像/字体库的完整汇总](LICENSES/dependencies/pillow-12.3.0/licenses/LICENSE) |
| Playwright Python | 1.64.1 | [Apache-2.0](LICENSES/dependencies/playwright-1.64.1/licenses/LICENSE)；驱动及第三方文本见下文 |
| greenlet | 3.5.6 | [MIT](LICENSES/dependencies/greenlet-3.5.6/licenses/LICENSE) 与 [PSF-2.0](LICENSES/dependencies/greenlet-3.5.6/licenses/LICENSE.PSF) |
| pyee | 14.0.0 | [MIT](LICENSES/dependencies/pyee-14.0.0/licenses/LICENSE) |
| PyYAML | 6.0.3 | [MIT](LICENSES/dependencies/PyYAML-6.0.3/licenses/LICENSE) |
| typing_extensions | 4.16.0 | [PSF-2.0](LICENSES/dependencies/typing_extensions-4.16.0/licenses/LICENSE) |
| setuptools | 84.2.1 | [MIT](LICENSES/dependencies/setuptools-84.2.1/licenses/LICENSE) |
| backports.tarfile，经 setuptools 带入 | 1.2.0 | [原始 LICENSE](LICENSES/dependencies/backports.tarfile-1.2.0/LICENSE) |
| jaraco.text，经 setuptools 带入 | 4.0.0 | [MIT](LICENSES/dependencies/jaraco.text-4.0.0/LICENSE) |
| jaraco.context，经 setuptools 带入 | 6.1.0 | [MIT](LICENSES/dependencies/jaraco.context-6.1.0/licenses/LICENSE) |
| jaraco.functools，经 setuptools 带入 | 4.4.0 | [MIT](LICENSES/dependencies/jaraco.functools-4.4.0/licenses/LICENSE) |
| more-itertools，经 setuptools 带入 | 10.8.0 | [MIT](LICENSES/dependencies/more-itertools-10.8.0/licenses/LICENSE) |
| tomli，经 setuptools 带入 | 2.4.0 | [MIT](LICENSES/dependencies/tomli-2.4.0/licenses/LICENSE) |
| wheel，经 setuptools 带入 | 0.46.3 | [MIT](LICENSES/dependencies/wheel-0.46.3/licenses/LICENSE.txt) |
| PyInstaller 启动器与运行时模块 | 6.22.3 | [GPL-2.0-or-later、启动器例外及运行时模块 Apache-2.0 条款](LICENSES/dependencies/pyinstaller-6.22.3/licenses/COPYING.txt) |
| PyInstaller 社区运行时钩子 | 2026.9 | [完整许可；运行时钩子为 Apache-2.0](LICENSES/dependencies/pyinstaller-hooks-contrib-2026.9/licenses/LICENSE) |

CustomTkinter 5.2.2 的 `METADATA` 的 `License` 字段写的是 “Creative Commons Zero v1.0 Universal”，但 wheel 实际附带的 `LICENSE` 为 MIT。这里完整保留实际 MIT 文本，不把这个元数据字段当作 CC0 授权。其内附 Roboto 字体另按 Apache-2.0 保留许可。

certifi 中未修改的证书包及其来源仍适用 MPL-2.0。可从 [certifi 2026.1.4 的公开发行页](https://pypi.org/project/certifi/2026.1.4/#files) 获取对应源码发行包，也可在 [Mozilla 的证书源文件](https://hg.mozilla.org/mozilla-central/file/tip/security/nss/lib/ckfw/builtins/certdata.txt) 查看证书数据来源。MPL 适用文件的许可和源码获取权利不受本应用许可限制。

## Playwright 内置 Node.js 与 JavaScript 组件

Python wheel 版本为 **1.64.1**；其中 `driver/package/package.json` 标记的 JavaScript 驱动版本为 **1.64.0-beta-1791568591000**，内置 `node.exe --version` 返回 **v24.22.1**。这些数值来自本次实际分发文件，不能互相替代。

以下原文均从该 wheel 逐字复制：

- [Node.js 及它内嵌组件的完整许可汇总](LICENSES/dependencies/playwright-1.64.1/driver/LICENSE)
- [Playwright driver LICENSE](LICENSES/dependencies/playwright-1.64.1/driver/package/LICENSE) 与 [NOTICE](LICENSES/dependencies/playwright-1.64.1/driver/package/NOTICE)
- [ThirdPartyNotices.txt](LICENSES/dependencies/playwright-1.64.1/driver/package/ThirdPartyNotices.txt)
- [utilsBundle.js.LICENSE](LICENSES/dependencies/playwright-1.64.1/driver/package/lib/utilsBundle.js.LICENSE)
- [serverRegistry.js.LICENSE](LICENSES/dependencies/playwright-1.64.1/driver/package/lib/serverRegistry.js.LICENSE)
- [webp_codec.LICENSE](LICENSES/dependencies/playwright-1.64.1/driver/package/lib/webp_codec.LICENSE)

便携包应保留驱动原有位置的这些文件，同时分发上面的集中副本。`ThirdPartyNotices.txt` 明确要求结合各 bundle 旁的 `.LICENSE` 查看，所以只附一份 Apache-2.0 不足以表达驱动全部依赖的许可。

本次范围不含浏览器二进制。若以后将 Chromium、Chrome、Edge 或 Playwright 下载的浏览器一起放入便携包，需要另外收集那个具体浏览器发行版本的许可与第三方通知；使用用户已经安装的浏览器不等于分发浏览器。

## Python 与原生运行时

| 组件 | 实际版本及依据 | 原文 |
| --- | --- | --- |
| CPython Windows x64 | 3.13.3，构建解释器 `sys.version` | [完整 Python LICENSE.txt](LICENSES/dependencies/Python-3.13.3/LICENSE.txt)，包括 PSF、历史许可、该 Windows 发行版的 Microsoft 附加分发条件、bzip2、OpenSSL、Tcl/Tk 文本 |
| Tcl | 8.6.15，实际 Tcl patchlevel 和 DLL 版本 | [Tcl license.terms](LICENSES/dependencies/Tcl-8.6.15/license.terms) |
| Tk | 8.6.15，实际 DLL 版本 | [Tk license.terms](LICENSES/dependencies/Tk-8.6.15/license.terms) |
| OpenSSL，由 Python `_ssl`/`_hashlib` 使用 | 3.0.16，运行时报告及 `libcrypto-3.dll` 版本 | [Apache-2.0](LICENSES/dependencies/OpenSSL-3.0.16/LICENSE.txt) |
| OpenSSL，静态包含在 cryptography wheel | 4.0.0，cryptography backend 与 wheel SBOM | [Apache-2.0](LICENSES/dependencies/OpenSSL-4.0.0/LICENSE.txt) |
| libffi，由 `_ctypes` 使用 | CPython 3.13.3 官方构建依赖为 3.4.4；当前 `libffi-8.dll` 未提供版本元数据 | [MIT](LICENSES/dependencies/libffi-3.4.4/LICENSE) |
| zlib | 1.3.1，实际运行时报告及 DLL 版本 | [zlib LICENSE](LICENSES/dependencies/zlib-1.3.1/LICENSE) |
| Expat | 2.7.1，`pyexpat.EXPAT_VERSION` | [CPython 3.13.3 源树中的 Expat COPYING](LICENSES/dependencies/expat-cpython-3.13.3/COPYING) |
| mpdecimal | 4.0.0，`_decimal.__libmpdec_version__` | [COPYRIGHT.txt](LICENSES/dependencies/mpdecimal-4.0.0/COPYRIGHT.txt) |
| XZ/liblzma，由 `_lzma` 使用 | CPython 3.13.3 官方构建依赖为 5.2.5 | [COPYING](LICENSES/dependencies/xz-5.2.5/COPYING)：本次相关的是 public-domain liblzma；不分发 XZ 的命令行工具、脚本或构建系统 |
| Microsoft VC/UCRT 运行时 | 当前 `VCRUNTIME140.dll` 为 14.42.34438.0 | 保留 [Python Windows 发行版的附加分发条件](LICENSES/dependencies/Python-3.13.3/LICENSE.txt)；这些 Microsoft 组件不由本应用的许可重新授权 |

libffi、XZ 的版本推定依据为 [CPython v3.13.3 的官方外部依赖清单](https://github.com/python/cpython/blob/v3.13.3/PCbuild/get_externals.bat)，没有把无法直接读取的二进制版本写成运行时实测。

Python DLL、标准库和 Tcl/Tk 未作代码修改，由 PyInstaller 选择并集中放入便携包；冻结、文件布局与应用模块属于本应用的打包安排。

## cryptography 的 Rust 组件

完整保留 wheel 自带的 [Rust CycloneDX 清单](LICENSES/dependencies/cryptography-48.0.0/sboms/cryptography-rust.cyclonedx.json) 和 [原生 OpenSSL 清单](LICENSES/dependencies/cryptography-48.0.0/sboms/sbom.json)。以该 Rust 清单为范围，从 **32 个具体版本的 crates.io 原始发行包** 中只取出 LICENSE、NOTICE、COPYING 等许可文件，保存在 [`rust-dependencies/`](LICENSES/dependencies/cryptography-48.0.0/rust-dependencies/)。没有把 crate 源码或缓存放入便携包。

范围包含 wheel 声明的构建辅助/宏组件，清单本身并不证明每个 crate 的机器码都留在最终 Windows 模块里；保留其通知可覆盖这个静态编译边界。cryptography 自有的七个 Rust 子组件使用 cryptography 的主许可。

多数 crate 为 MIT/Apache-2.0 双许可；`self_cell` 使用其 Apache-2.0 选项，保留全文；`target-lexicon` 的 Apache-2.0 LLVM 例外、`unicode-ident` 的 Unicode 许可均随各 crate 原文一同保存。各具体版本、公开下载 URL、原始 crate 压缩包 SHA-256 和所取文件 SHA-256 均列于 `MANIFEST.json`，不以一张泛称 MIT 的清单替代它们。

## 字体和 Pillow 内嵌库的致谢

CustomTkinter 内附的 Roboto Regular/Medium 字体在字体自身的元数据中标为 **Version 2.137; 2017**，声明 **Copyright 2011 Google Inc. All Rights Reserved.** 和 **Apache License, Version 2.0**。保留 [Roboto 的许可全文](LICENSES/dependencies/Roboto-2.137/LICENSE-APACHE.txt) 与 [字体内嵌声明的转录](LICENSES/dependencies/Roboto-2.137/NOTICE.txt)。CustomTkinter 自有形状字体随其 MIT 许可保存。

Pillow 的原始 wheel 汇总文件同时保存 Brotli、FreeType、HarfBuzz、libjpeg-turbo、libpng、libtiff、libwebp、OpenJPEG、zlib-ng 等所带组件的许可。对于 FreeType 使用其 FTL 选项，相关致谢如下：

> This software is based in part on the work of the FreeType Team.
> https://www.freetype.org/
>
> This software is based in part on the work of the Independent JPEG Group.

## 构建时必须一并复制

将本文件和完整 `LICENSES/dependencies/` 放在便携包根目录下，保持目录内所有文件和相对路径；不要只复制表格中的主许可证。还须保留 Playwright 驱动目录中原有的许可证和 NOTICE，并分发项目其他部分的第三方声明。

本次清单不覆盖游戏图标/商标、其他仓库改编代码的许可、用户自行加入的插件和未来另行下载的浏览器；那些部分由各自的来源与许可声明覆盖。更换 Python、wheel 或 Node/driver 后，应按新构建重做版本及通知核对，不能沿用本清单当作新版本已核验。
