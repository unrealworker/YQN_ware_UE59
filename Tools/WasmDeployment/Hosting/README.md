# 外部 Web 服务器配置参考

这三份配置由 UE Wasm 静态部署模板调整，已核对本次打包资源扩展名，并通过 `web.config` XML 解析检查；未在 IIS、nginx 或 Apache 主机上实机验收。包内 `Start-Local.bat` / `Start-LAN.bat` 使用独立的 Python 服务，不读取本目录配置。

- IIS：将 `web.config` 复制到 `Wasm/`，网站物理路径设为该目录，在 IIS 管理器中配置受客户端信任的 HTTPS 绑定。
- nginx：将 `nginx.conf` 中的 `server` 块放到现有 `http` 配置内，替换 `server_name`、`root`、`ssl_certificate` 和 `ssl_certificate_key`。Windows 路径使用正斜杠。启动前运行 `nginx -t`。
- Apache 2.4：将 `.htaccess` 复制到 `Wasm/`，将其设为 HTTPS 虚拟主机的 `DocumentRoot`，启用配置头部列出的模块和 `AllowOverride` 权限，并在虚拟主机设置可信证书。启动前运行 `httpd -t` 或 `apachectl configtest`。

仅公开 `Wasm/`，Runtime、Hosting 和 TLS 私钥应留在网站根目录之外。客户端使用的域名或 IP 必须在证书 SAN 中；内网 CA 的根证书需要由客户端信任。

IIS 和 nginx 示例直接发送原始文件，支持引擎读取容器所需的字节范围请求。Apache 示例可以协商已有 `.br` 文件，保留原始 MIME 类型与 `Content-Encoding: br`，并让 Range 请求读取未压缩文件。`_headers` 是其他托管平台的部署元数据，`.tmp` 是临时文件，均不是应用资源。

上线时检查首页及内嵌 HUD 的 CSS/字体无 MIME 错误、`crossOriginIsolated` 为 `true`、`navigator.gpu` 可用，并检查 `.ucas` 的 Range 请求返回 `206`。检查三项隔离响应头：`Cross-Origin-Opener-Policy: same-origin`、`Cross-Origin-Embedder-Policy: require-corp`、`Cross-Origin-Resource-Policy: same-origin`。

配置依据：[Apache 多扩展文件的 MIME 与编码](https://httpd.apache.org/docs/2.4/mod/mod_mime.html#multipleext)、[IIS MIME 映射](https://learn.microsoft.com/en-us/iis/configuration/system.webserver/staticcontent/mimemap)。
