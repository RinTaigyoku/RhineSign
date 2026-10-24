<p align="center"><img src="assets/icon.png" width="96" alt="RhineSign"></p>

<h1 align="center">RhineSign</h1>

<p align="center">Apple ID 个人签名与 iPhone USB 安装。Windows 桌面工具。</p>

我做这个工具，是想把选择 IPA、个人签名和安装放到一个窗口里。账号认证失败时，至少能看清失败在哪一步，而不是只得到一句“账号或密码错误”。

支持中文和英文。由 **RinTaigyoku** 维护；这是社区工具，与 Apple 没有官方合作关系。

## 下载

从 [Releases](https://github.com/RinTaigyoku/RhineSign/releases) 下载 Windows x64 压缩包，完整解压后打开 `RhineSign.exe`。不要单独移动 EXE，旁边的 `_internal` 也要保留。

目前是 **0.5.1 Beta**。个人签名沿用已实际使用过的认证流程；USB 安装的设备兼容性还需要更多实测。构建和离线检查通过，不代表所有 iOS 版本都能安装成功。

## 怎么用

1. 安装 Apple 官方的 Windows 设备驱动与设备服务。电脑已经能通过 Apple Devices 或 iTunes 识别手机的话，通常可以直接用。
2. 数据线连接 iPhone，解锁，在手机上信任电脑。打开“设备安装”，刷新并连接设备，UDID 会带到签名页。
3. 在“个人签名”填写 Apple ID、登录密码，选择任意 IPA。阅读设置里的服务说明，勾选同意后开始。需要双重认证时，在弹窗输入验证码。
4. 签名完成后，到程序旁的 `签名输出` 找到新 IPA。原文件不会覆盖。可以勾选签名完成后安装，也可以在“设备安装”单独选择已有签名的 IPA。

安装会再次显示文件和目标设备。同包名应用可能覆盖更新，程序不会为了安装而自动卸载旧 App。重要数据请自己备份。首次运行个人签名应用时，还可能需要在手机设置中信任开发者、启用开发者模式。

## 几个常见问题

**7460 是密码错了吗？** 不是。它表示个人开发证书数量达到上限。工具会列出现有证书，默认不选、不撤销。只有你选择一张，并在第二个确认框确认，才会替换这一张。依赖旧证书的其他自签 App 可能需要重新签名；不认识的证书不要随便撤销。

**免费账号能一直用吗？** 有效期、设备数、App ID 与安装数量由 Apple 限制，工具不能取消这些限制。过期需要重新签名。

**什么包都能签吗？** 暂时不支持包含 App Extension 的 IPA，也不能把受 App Store 加密保护的可执行文件直接变成可重签版本。安装功能同样不能绕过签名验证。

**识别不到手机怎么办？** 先检查数据线、解锁和信任状态，再检查 Apple Mobile Device Service。只支持 USB，不会自动连接网络设备。

**会保存密码吗？** 默认不保存。勾选“记住 Apple ID 和密码”后，用 Windows 当前用户加密保存在程序旁 `.rhinesign-account.dpapi`，下次打开自动填入。取消勾选就删除，验证码和登录会话始终不保存。认证请求发送给 Apple，认证辅助数据来自第三方 `ani.iloader.app`。签名私钥同样由 Windows 当前用户加密，存放在 `.签名密钥`，用于复用证书；不要分享账号缓存和密钥目录。配对记录由 Apple 本地设备服务管理。没有遥测、后台自动更新或自动撤销证书。

**大 IPA 会不会很占内存？** USB 传输使用固定 1 MiB 缓冲，不整包读入内存。签名需要解包和重新压缩，磁盘建议预留原 IPA 大小三倍的空间。取消可能留下临时构建目录，确认没有任务运行后可以删除 `临时构建`；不要删除密钥目录。

## 源码与构建

窗口使用 Python/Qt，认证与签名、USB 连接和安装使用 Rust。签名依赖固定版本，并包含嵌套动态库权限格式修正；签名后会检查代码结构，再重新打包并核验资源。

```powershell
python -m pip install PySide6-Essentials==6.10.0
python patch_signing_dependency.py
cargo test --locked --release --manifest-path engine/Cargo.toml
cargo build --locked --release --manifest-path engine/Cargo.toml
python -m unittest discover -s tests -v
python -m pip install pyinstaller==6.16.0
python scripts/package.py
```

Windows 发布流程在 `.github/workflows/build.yml`。发布附带校验和、依赖许可和对应源码，修改后可以重新编译并替换 `_internal/engine/rhinesign-engine.exe`。Python 3.12，Rust stable。

自己的代码采用 MIT 许可。依赖保留各自许可，特别是修改后的 `apple-codesign-quick` 采用 LGPL-2.1-or-later，对应源码随每次发布提供。

## English

RhineSign is a Windows desktop app for Apple ID personal signing and USB installation of signed IPAs. Maintained by **RinTaigyoku**. Switch the interface language with **中文 / EN**; the choice is remembered locally.

Download the Windows x64 archive from [Releases](https://github.com/RinTaigyoku/RhineSign/releases), extract the entire folder and run `RhineSign.exe`. Install Apple's device drivers/services, connect and trust your iPhone, then choose a device. Sign an arbitrary IPA with your Apple ID, or install an already signed IPA without signing in again. Existing apps are never automatically uninstalled.

This is a **beta**. USB installation is new and has not been verified across devices. Apple account limits, expiry, signature verification and Developer Mode still apply. Signing IPAs containing App Extensions is not supported yet.

Remembering the Apple ID and password is off by default. If enabled, Windows encrypts them for the current user in `.rhinesign-account.dpapi`; unchecking removes them. Verification codes and login sessions are never saved. Authentication goes to Apple; helper data comes from `ani.iloader.app`. Private signing keys are also encrypted for the current Windows user. Do not share account caches, the private-key folder or pairing records. No telemetry or automatic certificate revocation.

Build instructions are above. Source is MIT; dependencies retain their licenses. Corresponding source for the patched LGPL signing library is included in each release. This is an unofficial community project.
