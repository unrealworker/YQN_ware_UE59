# 原生网页的独立入口

`wasm-web-route.js` 将现有 HTTP 服务的 `/web/` 转发到本机 `127.0.0.1:8800`。不修改其它请求；公网 HTTPS 仍由已有入口终止。`/web` 会保留查询参数并重定向到带尾斜杠的 `/web/`。

## 集成

将 `wasm-web-route.js` 放在正式像素流服务的 `server/service.js` 同目录。在 `service.js` 顶部加入：

```js
const { handleWasmWeb } = require('./wasm-web-route');
```

在 `handlePublic` 的 `try` 中、解析 URL 后和原有路由之前加入：

```js
if (handleWasmWeb(req, res)) return;
```

通过现有启动器重新加载服务才能生效，接入前先保留原文件备份并确认在线会话。不要另起第二个 8080 服务。

## 行为

- 只允许 `/web` 与 `/web/*` 的 GET/HEAD；原首页、`/health`、`/api/session`、`/ws` 及其它路径继续使用原处理器。
- 上游地址固定为本机，URL 不能指定其它目标。拒绝目录穿越、反斜杠、无效编码及控制字符。
- 请求保留静态资源相关头，包括 Range 与 Accept-Encoding；Host 改为本机后端地址，不转发 Cookie、Authorization 或逐跳头。
- 流式转发状态码和资源头，保留 MIME、Content-Length、Content-Range、Content-Encoding、缓存规则及 COOP/COEP/CORP；不缓冲整个 Wasm 文件，不向共享域名设置后端 Cookie。
- 客户端退出会取消上游下载；上游不可用返回 502，连续 300 秒没有上游活动返回 504。已发送响应头后出现传输错误会终止响应，不伪造成功文件。

## 验证

```powershell
& 'C:/YQNwarhouse/pixelStreaming/Package_PixelStreaming2_20261030/runtime/node.exe' --test Tools/WasmDeploymentProxy/wasm-web-route.test.js
```

6 项测试通过：原路由隔离与重定向、Range/Brotli/安全相关响应头、HEAD/404、非法请求、502/504、客户端取消下载。测试使用临时本机端口并自行关闭，不连接现有像素流服务。

正式接入后还需从 HTTPS 入口验证 `/web/`、CSS 与 Wasm Range 206，运行 WebGPU 页面确认安全上下文及跨源隔离；同时复核根路径和像素流健康检查。代理模块不会自行安装服务、打开端口或修改云端规则。
