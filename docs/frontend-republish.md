# 前端「再次发布」操作手册（供新任务直接执行）

> 目标：把 `web/frontend` 的最新代码发布到固定的公网链接，供「智玩搭档」平台 iframe 挂载。
> 适用场景：前端源码（`src/`）有任何改动后需要同步到线上。

## 一、固定信息（不要改）

| 项目 | 值 |
|---|---|
| 源码目录 | `web/frontend`（Vue3 + Vite） |
| 构建产物 | `web/frontend/dist`（发布的是它，不是源码目录） |
| 线上链接 | `https://ec79b4b49f744ae3b577424cb5e33ddb.app.workbuddy.host`（固定不变，重复发布即覆盖更新） |
| 平台挂载入口 | `https://smtplay.cabyss.cn/mods/starrail?url=<编码后的前端URL>` |
| 平台挂载完整示例 | `https://smtplay.cabyss.cn/mods/starrail?url=https%3A%2F%2Fec79b4b49f744ae3b577424cb5e33ddb.app.workbuddy.host%2F%3Fplatform%3D1%26uid%3D1971189220` |

挂载 URL 的 `url` 参数**必须整体 URL 编码**，其内含两个必要查询参数：
- `platform=1`（强制平台桥接模式）
- `uid=1971189220`（指令路由目标 `mod:{uid}:starrail` 的用户 id）

## 二、标准流程（三步）

1. **构建**（在 `web/frontend` 下）：
   ```bash
   npm run build
   ```
   成功标志：输出 `dist/assets/index-XXXX.js`（文件名 hash 会变，属正常）。

2. **发布**：调用「发布为应用」能力，参数：
   - `directory`: `web/frontend/dist` 的绝对路径
   - `language`: `static`
   - `appName`: `星穹铁道助手前端`
   - 重复发布会覆盖线上内容，**必须先征得用户同意**（工具会强制要求确认）。
   发布成功后链接不变，返回 `verified: true` 即生效。

3. **验证**：
   - 浏览器打开线上链接，F12 确认加载的是**新 hash 的 bundle**（`index-XXXX.js`）；
   - 平台挂载页需**F5 强刷**才会让 iframe 拉到新版本（旧 bundle 可能被 iframe 缓存）。

## 三、注意事项 / 已踩过的坑

1. **先 build 后发布**：发布工具按目录原样上传，跳过 build 会把旧 dist 发上去。
2. **SDK 已 vendor 本地**：`src/js/smtplay-sdk-bridge.js`、`smtplay-sdk-message.js` 拷贝自平台 `/sdk/`。**不要改回远程 import**——HTTPS 前端加载 http 资源会被浏览器当混合内容拦截。
3. **平台模式判定**：`src/js/platform.js` 里 `isPlatformMode`（iframe 内或 `?platform=1`）。平台模式下登录态是本地假实现（`authenticated: true`），**页面能打开 ≠ 链路通**，必须点按钮发指令验证。
4. **诊断日志**：F12 过滤 `spb-pf` 可看到桥接收发（`发送指令 operate=...` / `收到消息 type=...`）。`平台桥回包首次到达` 只说明中继活着；event 的 requestId 是 mod 自生成的，与指令 requestId 不同属正常。
5. **平台控制台 WS 会话 15 分钟过期**：指令全部超时且从未收到回包时，先让用户强刷平台页（F5）再排查。
6. **本改动只涉及前端**：mod（`mods/starrail/`）或 client 改动不在发布范围内，需各自重启进程才能生效。
7. **不要尝试本机/局域网部署来替代**：平台页（公网）加载私网/localhost 前端会被 Chrome PNA 拦截，公网托管是硬要求。
8. **webapi（REST 模式）不受影响**：本发布只服务平台挂载；localhost 直连前端走 webapi，与线上链接无关。

## 四、回滚

线上内容被覆盖后无法在 WorkBuddy 侧回滚；如需回滚，用 git 切回旧版本重新执行「标准流程」即可（bundle hash 变化即代表版本切换）。
