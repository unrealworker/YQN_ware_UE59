# UE 5.9 原生网页与官方 MCP

本项目使用本机 `C:\UE\UE_5.9`（5.9.0，CL 60351404）。网页目标为 Wasm Shipping，浏览器在本地运行 WebAssembly/WebGPU。游戏及编辑器默认关卡均为 `/Game/Maps/GHS_GlobalWarehouse`，保留全球导航所需的两张仓库地图。

## 编译与打包

使用 PowerShell 7.2 或更新版本执行 `Scripts/ghs/package_wasm59.ps1`。默认 SDK 为 `Saved/Toolchains/emsdk`，必须为已激活的 Emscripten 6.0.10；可传 `-EngineRoot`、`-EmsdkRoot`、`-OutputDirectory`。Windows 编译仍需 MSVC 和 Windows SDK。

```powershell
pwsh -ExecutionPolicy Bypass -File Scripts/ghs/package_wasm59.ps1
```

默认输出为 `Deployment/GHSWeb59/Wasm`。脚本先编译编辑器，再执行 BuildCookRun 和 Epic `check_stage.py`。在 Codex 内执行须使用命令级构建授权，因为引擎及用户日志/缓存不在项目可写目录内。打包时通过命令行排除 AllToolsets，避免 UE 5.9 Preview 的 GameFeatureData 烘焙问题；日常编辑器仍启用官方 MCP 工具集。

`TestGame.Target.cs` 的 Wasm Shipping 使用引擎支持的 O2 链接优化，C++ 仍按 Shipping 编译。首次烘焙需要生成移动 forward/deferred 两套着色器和平台资源，后续可复用缓存。

打包脚本自动调用 `finalize_wasm_web_assets.ps1` 修正 UE 5.9 Preview 生成的 Service Worker 的 MIME 映射，并重建其 Brotli 文件。官方模板仅识别 JS/Wasm，会使缓存的 HUD CSS 被当作二进制而失去样式；修正脚本识别已知模板并验证压缩内容，遇到未知版本会停止以便复核。

桌面 Pixel Streaming 代码仅在非 Wasm 平台编译。Wasm 的 HTML HUD 使用同源 iframe 和游戏线程命令桥；默认使用官方移动 forward/deferred WebGPU 渲染层，画面不保证与桌面 Lumen/Nanite 完全相同。

## 本机与局域网访问

本机预览：

```powershell
powershell -ExecutionPolicy Bypass -File Scripts/ghs/serve_wasm59.ps1
```

打开 `http://127.0.0.1:8800/`。不能双击 `index.html` 通过 `file://` 运行。

局域网需要管理员准备一份客户端信任的 HTTPS 证书；证书的 SAN 必须覆盖实际使用的域名或 IP。域名应通过内网 DNS 指向此服务器。内部 CA 的根证书需要在客户端受信任；仅点击浏览器证书警告并不能可靠提供 WebGPU 安全上下文。

```powershell
powershell -ExecutionPolicy Bypass -File Scripts/ghs/serve_wasm59.ps1 `
  -BindAddress 0.0.0.0 -Port 8800 `
  -Certificate C:\Certificates\warehouse.crt `
  -PrivateKey C:\Certificates\warehouse.key `
  -AllowedHosts warehouse.example.internal
```

客户端打开 `https://warehouse.example.internal:8800/`。若证书覆盖 IP，则使用该 IP，并在 `-AllowedHosts` 中传入它。在 Windows 防火墙中仅向所需局域网网段开放 TCP 8800；本次脚本不会自动修改防火墙或创建证书。网页服务运行期间保留该进程。

2026-11-17 检查到本机以太网地址 `10.100.185.162`、OpenVPN 地址 `10.8.0.39`。同一以太网/可路由内网可使用前者；VPN 客户端可在路由允许时使用后者。对应示例为 `https://10.100.185.162:8800/` 或 `https://10.8.0.39:8800/`，仍须满足证书、路由与防火墙要求；这里只记录地址，未声称已对外开放或通过其他设备验收。

脚本调用引擎官方 `serve.py`，提供 WebGPU 所需的 COOP/COEP/CORP 响应头、Brotli 与 Range 请求。长期部署也可将打包目录交给 IIS/nginx，配置 HTTPS 和同等响应头。客户端推荐支持 WebGPU 的 Chrome/Edge，首次访问需要下载内容并编译着色器。

## 官方 MCP

`Test.uproject` 启用 Epic `ModelContextProtocol` 和编辑器工具集，关闭旧第三方 `UE_MCP_Bridge`。项目 `.codex/config.toml` 指向 `http://127.0.0.1:8000/mcp`。MCP 仅用于本机编辑器控制，不是网页用户入口，不应开放到局域网。

启动 UE 5.9 编辑器并打开本项目后，可运行只读验证：

```powershell
& C:\UE\UE_5.9\Engine\Binaries\ThirdParty\Python3\Win64\python.exe Scripts/ghs/verify_unreal_mcp59.py
```

验证执行 MCP 初始化、发现工具集、读取当前关卡和 Actor，并核对项目路径和引擎版本。证据写在 `Saved/UE59Web/mcp-verification.json`。构建与浏览器验收记录亦保存在 `Saved/UE59Web`。

参考：Epic [Unreal MCP](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor)；本机 `Engine/Platforms/Wasm/Docs` 和 `Skills/web-deploy/SKILL.md`。

## 2026-11-17 首版验收（已由 r2 替代）

- 最终 `TestEditor Win64 Development`、`TestGame Wasm Shipping` 均编译成功；烘焙与网页归档成功。
- `check_stage.py` 全部通过，发布扫描 0 项发现；有 1 条引擎内置字体历史导入路径提示。
- 本机 Edge 157 / NVIDIA A10 冷缓存、未限速测试：deferred READY 5.776 秒，forward READY 4.850 秒；两者 WebGPU 错误为 0，Wasm 内存峰值 512 MiB。时间仅代表本机测试条件。
- 真实页面的中文字体、CSS、地图和仓库卡片正常；点击 GHS 加州仓库，游戏与 DOM 同步选中 `ghs-ca`。未逐项验收两座仓库的全部业务交互。
- 官方 MCP 最终连接返回 UE 5.9.0-60351404、当前关卡 `/Game/Maps/GHS_GlobalWarehouse` 和 12 个 Actor；地图 SHA256 与本次验证前一致。
- 界面桥接测试 7/7、打包 MIME 修正回归测试 2/2 通过。
- 网页目录：`Deployment/GHSWeb59/Wasm`；调试文件单独位于同级 `Wasm-Debug`，无需发布。
- 静态主机配置计划：`Deployment/GHSWeb59-HostingPlan`，包含 IIS `web.config`、nginx 和 Apache 示例；没有上传或部署到外部服务器。
- 原生网页采用移动 forward/deferred 渲染层；与桌面 Lumen/Nanite 画面不完全等价。当前纹理包针对支持 BC 压缩的桌面 Chrome/Edge，未验证手机兼容。

最终证据：`Saved/UE59Web/build-editor-final.log`、`build-wasm-final.log`、`cook-wasm.log`、`package-wasm.log`、`browser-deferred-final/result.json`、`browser-forward-final/result.json`、`hud-mime/interaction.json`、`hud-mime/check-stage-after.json` 和 `mcp-verification.json`。

## 2026-11-17 修订版 r2 与便携部署

交付目录为 `Deployment/GHS-Warehouse-Web-UE59-20261117-r2`，同名 `.zip` 可完整解压到其他 Windows x64 电脑。包内 Python 运行环境不依赖 UE 或系统 Python。运行 `Start-Local.bat` 验证本机；局域网部署按包内 `部署说明.md` 配置受信任证书及 `server.json`，再运行 `Start-LAN.bat`，用户访问 `https://服务器域名或IP:8800/`。没有替目标电脑配置证书、DNS 或防火墙。

本次修复：

- MPR 木马作业仿真面板默认收起，仍可点击展开。
- 两个仓库的屋顶 ScanReveal 材质目录显式加入烘焙。首版实际 UAT 清单遗漏全部 12 个材质，导致 GHS 没有溶解过程、MPR 拒绝展开；新版清单验证 12/12。缺失材质时日志会记录具体对象。
- Wasm 全球关卡使用现有的 DOM 地理投影国家名称，保留背面剔除和标签避让；桌面国家标签不受影响。

`TestEditor Win64 Development`、Wasm Shipping 构建与烘焙成功；屋顶自动化测试 10/10、国家标签页面测试 23/23 通过。`check_stage.py` 全部通过，0 项发布发现；保留引擎字体历史导入路径提示。官方 MCP 重新验证通过，默认关卡和 12 个 Actor 正确，验证未改地图。

构建、实际 Cook 清单、发布检查和浏览器证据保存在 `Saved/UE59WebRevision2`。源地图保持原样。按用户约定保留无 Git 状态。

最终 r2 实测：

- A10 硬件 WebGPU 的两仓实际标签点击、屋顶溶解中段及完成打开、返回地球、返回后国家名全部通过；MPR 面板默认收起及展开/收起通过。每仓保存 46 帧，人工确认蓝色扫描边缘和部分保留屋顶。0 页面错误、0 失败请求。证据：`interactions-a10-deferred/result.json`、`animation-review.json`。
- 官方冷缓存、无限速启动：forward 实际为 `SP_WEBGPU_ES3_1`，READY 5.104 秒、READY 前下载 151,491,062 字节；deferred 实际为 `SP_WEBGPU_ES3_1_DEFERRED`，READY 4.862 秒、下载 157,327,277 字节。两者 WebGPU 错误 0，Wasm 内存峰值 512 MiB。时间仅代表本机测试条件。证据：`browser-forward-a10/result.json`、`browser-deferred-a10/result.json`。
- 本机默认自动化浏览器一度选择软件 GPU；仅在隔离测试进程使用高性能 GPU 参数后确认 `nvidia/ampere`。没有改系统驱动或发布页面，不用软件渲染数据代表硬件性能。
- 最终 ZIP 已解压到另一个带空格的目录，3056 个文件 SHA256 及包内 Runtime 路径全部通过；实际静态服务、全部 CSS、Wasm Range 206 及隔离响应头通过。证据：`portable-delivery.json`。
- 五张源地图 SHA256 与本次修复前一致（`maps-verified.json`）。四项旧网页包已删除（`removed-old-web-packages.json`），本机 8800 预览使用新版便携 Runtime。无关的 Pixel Streaming 目录保留。

可重复制作及验证便携包：

```powershell
pwsh -File Scripts/ghs/create_wasm_delivery.ps1 -ArchiveDirectory <UAT归档目录> -DeliveryDirectory <新的交付目录>
& Saved/Toolchains/emsdk/python/3.13.3_64bit/python.exe -I -B Scripts/ghs/verify_wasm_delivery.py --delivery <解压目录> --out <包外的报告路径.json>
```

交付脚本拒绝覆盖已有文件；生成逐文件 SHA256 清单和 ZIP 校验文件。校验工具使用包内 Runtime，验证完整性、实际静态服务、隔离响应头、CSS MIME 和 Wasm Range 206。`Hosting` 是 IIS/nginx/Apache 配置参考，未在这三类服务器上实机验收。
