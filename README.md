# Proxy Cleaner Console

给 `proxy_cleaner.py` 做的一个可视化 Web 控制台，适合把“配置、启动、观察日志、查看报告”这几件事集中到一个页面里处理。

## 适合谁用

如果你已经有自己的 `proxy_cleaner.py`，但不想每次都手敲命令、翻日志、手动找报告，这个小项目会比较顺手。

它提供：

- 参数填写与保存
- 一键启动 / 停止 / 重启 cleaner
- 一键重启 Web 控制台后端
- 一键执行 dry-run
- 查看 cleaner / web 日志
- 查看最近报告（默认前 5 个）
- 服务端密码校验（PBKDF2 哈希）
- HttpOnly + Secure + SameSite=Strict Cookie
- Host 白名单限制
- systemd 服务文件示例

## 页面

- 顶部状态卡片
- 自动刷新状态 / 日志
- 报告摘要弹窗
- 苹果风浅色 UI，移动端也能看

## 目录结构

```text
.
├── app.py
├── common.py
├── run_cleaner.py
├── proxy-cleaner.service
├── proxy-cleaner-web.service
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
└── README.md
```

## 运行原理

- `app.py`：WSGI 小后端，负责登录、状态查询、保存配置、控制 systemd、查看报告
- `common.py`：统一配置、校验、命令拼装
- `run_cleaner.py`：读取 `web_config.json` 后，用当前配置启动真实 cleaner
- `proxy-cleaner.service`：后台 cleaner 服务
- `proxy-cleaner-web.service`：控制台 Web 服务

## 为什么加 `run_cleaner.py`

一个常见坑是：

> 页面里保存了配置，但 systemd 的 `ExecStart` 还是写死参数，结果“看起来改了，实际没生效”。

这里用 `run_cleaner.py` 兜了一层，让 cleaner 每次都从 `web_config.json` 读取最新配置，再去启动实际任务。这样页面保存后，**重启 cleaner 服务即可真正生效**。

## 部署要求

- Linux
- Python 3.10+
- systemd
- Nginx（反代可选，但推荐）
- 已有可执行的 `proxy_cleaner.py`

## 快速部署

### 1. 上传项目

```bash
mkdir -p /opt/proxy-cleaner-console
cp -r ./* /opt/proxy-cleaner-console/
```

### 2. 安装 systemd 服务

```bash
cp proxy-cleaner.service /etc/systemd/system/proxy-cleaner.service
cp proxy-cleaner-web.service /etc/systemd/system/proxy-cleaner-web.service
systemctl daemon-reload
systemctl enable proxy-cleaner.service proxy-cleaner-web.service
```

### 3. 首次生成配置

第一次运行前，建议先手动创建 `/opt/proxy-cleaner-console/web_config.json`。

示例：

```json
{
  "listen_host": "127.0.0.1",
  "listen_port": 28717,
  "allowed_hosts": ["example.com", "127.0.0.1", "localhost"],
  "proxy_cleaner_path": "/root/proxy_cleaner.py",
  "state_file": "/root/proxy_cleaner_state.json",
  "base_url": "https://example.com/management.html",
  "management_key": "replace-me",
  "interval": 60,
  "enable_api_call_check": true,
  "api_call_url": "https://chatgpt.com/backend-api/wham/usage",
  "api_call_method": "GET",
  "api_call_account_id": "",
  "api_call_user_agent": "Mozilla/5.0 ProxyCleanerConsole/1.0",
  "api_call_body": "",
  "api_call_providers": "codex,openai,chatgpt",
  "api_call_max_per_run": 50,
  "api_call_sleep_min": 5.0,
  "api_call_sleep_max": 10.0,
  "revival_wait_days": 7,
  "revival_probe_interval_hours": 12,
  "password_salt": "请自行生成",
  "password_hash": "请自行生成"
}
```

> 仓库里故意不提交 `web_config.json`，避免把线上敏感配置直接带出去。

### 4. 启动服务

```bash
systemctl restart proxy-cleaner-web.service
systemctl restart proxy-cleaner.service
systemctl status proxy-cleaner-web.service --no-pager
systemctl status proxy-cleaner.service --no-pager
```

## Nginx 示例

假设你要把页面挂到 `/proxy-cleaner/`：

```nginx
location ^~ /proxy-cleaner/ {
    proxy_pass http://127.0.0.1:28717;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;

    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header Content-Security-Policy "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;
}
```

## 安全说明

这个项目默认做了几层比较基础但实用的保护：

- 控制台密码只保存 PBKDF2 哈希，不保存明文
- Cookie 开启 HttpOnly / Secure / SameSite=Strict
- Host 白名单校验
- 登录失败限流
- systemd 加了 `NoNewPrivileges=true`
- 使用 `ProtectSystem=full`

但还是建议你自己额外做这些：

- 不要暴露在任何人都能扫到的公网路径上，最好加 IP 限制或额外认证
- 反代层再套一层 Basic Auth / Access Policy 会更稳
- 首次部署后立刻更换默认控制台密码
- 把 `allowed_hosts` 改成你自己的正式域名
- 定期检查日志和报告目录权限

## 默认密码提示

仓库里的默认控制台密码只是占位用途，请在首次部署后马上改掉。

建议做法：

1. 先自己生成新的 PBKDF2 哈希
2. 写入 `web_config.json`
3. 重启 `proxy-cleaner-web.service`

如果你愿意，也可以扩展成“页面内修改控制台登录密码”，这个仓库已经预留了后端配置更新能力，补个前端字段就行。

## 已知限制

- 依赖 `systemctl` 控制服务，不适合没有 systemd 的环境
- 默认报告目录路径和 cleaner 运行路径，需要按你自己的环境改
- 这是一个偏实用型的单文件小后端，不是 Flask / FastAPI 工程化脚手架

## 适合继续加的功能

- 页面内直接修改控制台登录密码
- 多用户 / 多角色权限
- 报告筛选与搜索
- cleaner 服务运行历史图表
- Telegram / 企业微信告警推送
- Docker Compose 部署版

## License

本项目采用 **MIT License**，你可以在保留原始版权声明和许可证文本的前提下自由使用、修改、分发。
详细内容见仓库根目录的 `LICENSE` 文件。
