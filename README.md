# 淘宝客返利 MCP 服务器

把淘宝/天猫商品链接转换成专属返利推广链接，并支持按关键词搜索带返利的商品。以 [MCP](https://modelcontextprotocol.io)（Model Context Protocol）服务的形式对外提供，可直接接入 Claude 等支持 MCP 的客户端。

## 架构

本项目是「MCP 套 MCP」的两层结构：

- **外层**：FastMCP 的 Streamable HTTP 服务器（部署在 Zeabur 或任何能跑 Docker 的地方）
- **内层**：通过 `stdio_filter.py` 包装器调用 [sinataoke_cn](https://www.npmjs.com/package/@liuliang520500/sinataoke_cn)（淘宝客 API 的 MCP 封装），过滤它打到 stdout 的噪音日志，保证 JSON-RPC 通道干净

```
MCP客户端 ──HTTP──> server.py (FastMCP 外层)
                        │ stdio + 过滤
                        └──> stdio_filter.py ──> sinataoke_cn ──> 淘宝联盟API
```

## 提供的工具

| 工具 | 功能 |
|---|---|
| `convert_taobao_link` | 传入淘宝/天猫商品 URL，返回专属返利推广链接 |
| `search_taobao_products` | 按关键词搜索商品，返回标题/价格/促销/店铺/返利链接（默认 30 条） |
| `get_server_info` | 查看服务器运行状态 |

## 部署

### 方式一：Zeabur（推荐）

1. Fork 或导入本仓库到你的 GitHub
2. 在 Zeabur 新建服务，选择该仓库，**Root Directory 设为 `taobao/`**（Dockerfile 和 zbpack.json 都在这个子目录里）
3. 配置环境变量（见下表）
4. 部署完成后绑定域名即可使用

### 方式二：Docker 自托管

```bash
cd taobao
docker build -t taobao-mcp .
docker run -d -p 8080:8080 \
  -e TAOBAO_SESSION=你的session \
  -e TAOBAO_PID=你的pid \
  --name taobao-mcp taobao-mcp
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `TAOBAO_SESSION` | ✅ | 淘宝联盟授权 token，**会过期**，获取与续期见下文 |
| `TAOBAO_PID` | ✅ | 淘宝客推广位 PID，格式 `mm_开头的一串数字` |
| `PORT` | ❌ | 监听端口，默认 `8080` |

> 两个必填变量缺失或为空时，服务会在启动阶段直接报错退出，不会静默降级。

## 凭证获取

### TAOBAO_PID（推广位 ID）

1. 登录[淘宝联盟](https://pub.alimama.com/)
2. 进入 推广管理 → 推广位管理
3. 新建或查看已有推广位，复制 PID（格式形如 `mm_123456789_123456789_123456789`）

### TAOBAO_SESSION（授权 token）

1. 用你的淘宝账号登录后，在浏览器访问授权链接：

   ```text
   https://oauth.taobao.com/authorize?response_type=token&client_id=34297717&state=1212&view=web
   ```

2. 确认授权后页面会跳转，此时看浏览器**地址栏**，URL 里带着 `#access_token=xxxxx...`
3. 复制 `access_token=` 后面那串字符就是 `TAOBAO_SESSION`

> 建议把授权链接存到收藏夹，以后续期直接用。

## ⚠️ 凭证会过期

`TAOBAO_SESSION` 是 OAuth 授权 token，**不是永久有效的**，一般几个月左右就会失效（以淘宝实际返回为准）。

**过期的症状：**

- `convert_taobao_link` / `search_taobao_products` 调用报错或返回空结果
- 但 `get_server_info` 正常、服务本身没挂——因为只是 token 失效，不是服务崩溃

**过期后的处理：**

1. 重新访问上面的授权链接，拿一个新的 `access_token`
2. 更新部署平台的环境变量（Zeabur：Settings → Environment Variables）
3. 重新部署（Zeabur 改完环境变量会自动重部署）

`TAOBAO_PID` 是你的推广位 ID，不会过期，除非你自己在淘宝联盟后台删掉该推广位。

## MCP 客户端接入

服务以 Streamable HTTP 方式运行，默认端点为 `https://<你的域名>/mcp`。

以 Claude 为例，在 MCP 设置里添加：

```json
{
  "mcpServers": {
    "taobao": {
      "url": "https://your-app.zeabur.app/mcp"
    }
  }
}
```

接入后直接对话即可，例如：

- 「帮我搜一下蓝牙耳机，要带返利链接的」
- 「把这个链接转成返利链接：https://item.taobao.com/xxxxx.html」

## 安全说明

- 所有凭证**只**通过环境变量注入，源码里没有任何硬编码兜底值
- 千万不要把真实的 `TAOBAO_SESSION` / `TAOBAO_PID` 提交进仓库——哪怕是私有仓库，Git 历史也会永久保留，一旦转公开就泄露
- 服务日志不会打印凭证的实际值

## 技术细节

- **版本锁定**：sinataoke_cn 锁定在 `2.0.5`，防止上游推破坏性更新
- **全局锁**：同时只允许一个内层子进程运行，防止并发把 CPU 打爆
- **超时清理**：单次调用 45 秒超时，卡死的子进程会被自动清理
- **噪音过滤**：`stdio_filter.py` 只转发以 `{` 开头的行（JSON-RPC 消息），其余日志全部丢弃
