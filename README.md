# CLIProxyAPI-cleaner

中文 | [English](README_EN.md)

`CLIProxyAPI-cleaner` 是一个“**自动清理脚本 + Web 控制台**”一体化项目，用来管理和清理 CLIProxyAPI / auth-file 相关账号状态。

仓库默认首页是中文说明；如果你想看英文版，可以直接点上面的 **English**。

## 这个仓库包含什么

- `CLIProxyAPI-cleaner.py`：真正执行检测、禁用、删除、refresh、复活探测的主脚本
- `app.py`：轻量 Web 后端，负责登录、状态查询、保存配置、控制 systemd、查看报告
- `common.py`：配置加载、校验、命令拼装
- `run_cleaner.py`：读取 `web_config.json` 并按当前配置启动 cleaner
- `cleanup_retention.py`：独立的文件保留清理脚本，负责清理旧报告/备份并裁剪日志
- `CLIProxyAPI-cleaner.service`：后台清理服务
- `CLIProxyAPI-cleaner-web.service`：控制台服务
- `CLIProxyAPI-cleaner-retention.service` / `.timer`：定时文件清理服务与定时器
- `static/`：前端页面
- `web_config.example.json`：公开版示例配置

## 能做什么

- 参数填写与保存
- 一键启动 / 停止 / 重启 cleaner
- 一键重启 Web 控制台后端
- 一键执行 dry-run
- 查看 cleaner / web 日志
- 查看最近报告（默认前 5 个）
- 定时清理旧报告、旧备份，并自动裁剪过大的日志文件
- 登录限流、Host 白名单、Cookie 安全属性
- 支持 Docker / Docker Compose 部署

## 示例说明

文中涉及的账号场景、探测说明和相关描述，默认以 **codex** 为例；其他兼容 provider 的处理思路基本一致。

## 部署要求

- Linux
- Python 3.10+
- systemd
- Nginx（推荐，用于反代）
- 服务器具备访问上游 API 和你的管理端地址的网络能力

## 目录结构

```text
.
├── CLIProxyAPI-cleaner.py
├── app.py
├── common.py
├── run_cleaner.py
├── cleanup_retention.py
├── CLIProxyAPI-cleaner.service
├── CLIProxyAPI-cleaner-web.service
├── CLIProxyAPI-cleaner-retention.service
├── CLIProxyAPI-cleaner-retention.timer
├── web_config.example.json
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── Dockerfile
├── docker-compose.yml
├── docker/
│   ├── entrypoint.sh
│   ├── run_cleaner.sh
│   └── supervisord.conf
├── README.md
└── README_EN.md
```

## 部署原理

页面保存配置后，会写入 `web_config.json`。
`run_cleaner.py` 启动时会读取这份配置，再调用 `CLIProxyAPI-cleaner.py`。
这样就不会出现“页面里改了参数，但 systemd 仍然跑旧命令”的问题。

---

# 详细部署说明

## 1）获取代码

你可以直接 clone：

```bash
git clone https://github.com/KJ20051223/CLIProxyAPI-cleaner.git
cd CLIProxyAPI-cleaner
```

也可以在本地解压后再上传到服务器。

## 2）准备安装目录

推荐安装到：

```bash
mkdir -p /opt/CLIProxyAPI-cleaner
cp -r ./* /opt/CLIProxyAPI-cleaner/
cd /opt/CLIProxyAPI-cleaner
```

## 3）生成控制台登录密码哈希

仓库里的 `web_config.example.json` 只是示例，正式部署前建议先生成你自己的控制台密码哈希：

```bash
python3 - <<'PY'
import os, hashlib
password = 'change-me-now'
salt = os.urandom(16).hex()
digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 260000).hex()
print('password_salt =', salt)
print('password_hash =', digest)
PY
```

把输出的 `password_salt` 和 `password_hash` 写进配置文件。

## 4）创建正式配置文件

先复制示例配置：

```bash
cp web_config.example.json web_config.json
```

然后按你的环境修改：

```json
{
  "listen_host": "127.0.0.1",
  "listen_port": 28717,
  "allowed_hosts": ["your-domain.com", "127.0.0.1", "localhost"],
  "cleaner_path": "/opt/CLIProxyAPI-cleaner/CLIProxyAPI-cleaner.py",
  "state_file": "/root/CLIProxyAPI-cleaner-state.json",
  "base_url": "https://your-domain.com/management.html",
  "management_key": "your-management-key",
  "interval": 60,
  "enable_api_call_check": true,
  "api_call_url": "https://chatgpt.com/backend-api/wham/usage",
  "api_call_method": "GET",
  "api_call_account_id": "",
  "api_call_user_agent": "Mozilla/5.0 CLIProxyAPI-cleaner/1.0",
  "api_call_body": "",
  "api_call_providers": "codex,openai,chatgpt",
  "api_call_max_per_run": 50,
  "api_call_sleep_min": 5.0,
  "api_call_sleep_max": 10.0,
  "revival_wait_days": 7,
  "revival_probe_interval_hours": 12,
  "password_salt": "replace-with-your-generated-salt",
  "password_hash": "replace-with-your-generated-hash"
}
```

### 关键字段解释

- `cleaner_path`：主脚本路径
- `state_file`：状态文件，用来记录复活检查节奏
- `base_url`：你的管理端地址
- `management_key`：管理 API 所需密钥
- `allowed_hosts`：允许访问控制台的 Host 白名单
- `password_salt` / `password_hash`：控制台登录密码

## 5）安装 systemd 服务与文件清理定时器

```bash
cp CLIProxyAPI-cleaner.service /etc/systemd/system/CLIProxyAPI-cleaner.service
cp CLIProxyAPI-cleaner-web.service /etc/systemd/system/CLIProxyAPI-cleaner-web.service
cp CLIProxyAPI-cleaner-retention.service /etc/systemd/system/CLIProxyAPI-cleaner-retention.service
cp CLIProxyAPI-cleaner-retention.timer /etc/systemd/system/CLIProxyAPI-cleaner-retention.timer
systemctl daemon-reload
systemctl enable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service
systemctl enable --now CLIProxyAPI-cleaner-retention.timer
```

默认保留策略：

- 报告：最多保留最近 `200` 份，同时删除 `7` 天前的旧报告
- 备份：删除 `14` 天前的旧备份，并顺手清掉空目录
- 日志：`/root/CLIProxyAPI-cleaner.log` 和 `web.log` 超过 `50MB` 时自动裁剪，只保留最近内容

如果你想调整这些值，可以直接编辑：

- `CLIPROXY_KEEP_REPORTS`
- `CLIPROXY_REPORT_MAX_AGE_DAYS`
- `CLIPROXY_BACKUP_MAX_AGE_DAYS`
- `CLIPROXY_LOG_MAX_SIZE_MB`

## 6）配置 Nginx 反代

如果你想把控制台挂到 `https://your-domain.com/CLIProxyAPI-cleaner/`，可以加：

```nginx
location ^~ /CLIProxyAPI-cleaner/ {
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

改完后执行：

```bash
nginx -t && systemctl reload nginx
```

## 7）启动服务

```bash
systemctl restart CLIProxyAPI-cleaner-web.service
systemctl restart CLIProxyAPI-cleaner.service
```

## 8）检查运行状态

```bash
systemctl status CLIProxyAPI-cleaner-web.service --no-pager
systemctl status CLIProxyAPI-cleaner.service --no-pager
systemctl status CLIProxyAPI-cleaner-retention.timer --no-pager
```

看日志：

```bash
tail -f /opt/CLIProxyAPI-cleaner/web.log
tail -f /root/CLIProxyAPI-cleaner.log
```

## 9）首次访问

浏览器打开：

```text
https://your-domain.com/CLIProxyAPI-cleaner/
```

输入你在第 3 步生成对应的控制台密码即可登录。

## 10）后续更新

如果你后面从 GitHub 拉了新版代码：

```bash
cd /opt/CLIProxyAPI-cleaner
git pull
systemctl restart CLIProxyAPI-cleaner-web.service
systemctl restart CLIProxyAPI-cleaner.service
systemctl restart CLIProxyAPI-cleaner-retention.timer
```

如果更新中改了 service 文件，记得再执行：

```bash
systemctl daemon-reload
```

## Docker / Docker Compose 部署

如果你不想自己配 systemd，也可以直接用 Docker 跑。这个仓库现在已经内置一套可运行的 Docker 方案，附带：

- `Dockerfile`
- `docker-compose.yml`
- `docker/supervisord.conf`
- `docker/entrypoint.sh`
- `docker/run_cleaner.sh`

容器方案里：

- **web 和 cleaner 在同一个容器里**
- 由 **supervisor** 负责进程托管
- Web 控制台里的“启动 / 停止 / 重启 cleaner”在 Docker 模式下会自动改走 `supervisorctl`
- 默认把配置、日志、报告、备份都放到挂载目录 `./docker-data`

### 快速开始

```bash
git clone https://github.com/KJ20051223/CLIProxyAPI-cleaner.git
cd CLIProxyAPI-cleaner
docker compose up -d --build
```

首次启动后，会自动在 `./docker-data/web_config.json` 生成一份配置模板。
你只需要把里面这些值改成你自己的：

- `base_url`
- `management_key`
- `allowed_hosts`
- `password_salt`
- `password_hash`

改完后重新拉起容器，或者在页面里直接点启动 cleaner 即可。

### 常用命令

```bash
# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 停止
docker compose down

# 升级后重建
docker compose up -d --build
```

### 默认数据目录

Compose 默认把这些东西持久化到 `./docker-data`：

- `web_config.json`
- `logs/`
- `reports/`
- `backups/`
- `CLIProxyAPI-cleaner-state.json`

### 访问地址

默认端口映射是：

```text
http://你的服务器IP:28717/CLIProxyAPI-cleaner/
```

### Docker 模式注意事项

1. **本地直连 HTTP** 时，`docker-compose.yml` 默认把 `CLIPROXY_COOKIE_SECURE=false`，这样直接映射端口也能登录。
2. 如果你前面再套了 HTTPS 反代，建议把它改回：

```yaml
CLIPROXY_COOKIE_SECURE: "true"
```

3. `CLIPROXY_ALLOWED_HOSTS` 默认是 `*`，为了方便首次启动；正式使用时建议收紧成你自己的域名或 IP。
4. cleaner 容器启动后会先检查 `web_config.json` 是否已经填了真实的 `base_url / management_key`；如果还是示例值，会先等待，不会真的跑清理逻辑。
5. `cleanup_retention.py` 也会一并打进镜像；如果你用 Docker，建议在宿主机加 cron / timer，或手动执行它做报告/备份/日志保留清理。

---

## 安全建议

- 不要把控制台直接裸露到公网，最好再加 IP 限制或上游认证
- 首次部署后立刻替换默认示例密码
- `allowed_hosts` 不要保留 `example.com`
- 尽量只监听 `127.0.0.1`，通过 Nginx 暴露页面
- 定期检查日志与报告目录权限

## 常见问题

### 1. 页面能打开，但登录失败

优先检查：
- `web_config.json` 里的 `password_salt` / `password_hash` 是否和你生成的一致
- 是否重启了 `CLIProxyAPI-cleaner-web.service`

### 2. 页面里保存了配置，但 cleaner 没变化

重启：

```bash
systemctl restart CLIProxyAPI-cleaner.service
```

### 3. 页面 404 或静态资源加载失败

检查：
- Nginx 的 `location ^~ /CLIProxyAPI-cleaner/` 是否正确
- `app.py` 是否在跑
- 反代后有没有多余的路径重写

## 如何适配别的认证文件 / provider

当前仓库里默认实现，主要是**以 codex 认证文件为例**来写的，尤其是“额度号后续 refresh + 复活探测”这一段，默认依赖以下前提：

- 本地 auth-file 是 JSON 对象
- 文件里能拿到 `refresh_token`
- refresh 逻辑兼容 OpenAI family 的 token 接口
- refresh 成功后能拿到新的 `access_token`（以及可能的新 `refresh_token` / `id_token`）
- 后续可以通过配置的 `api_call_url` 再 probe 一次

如果你要接入**别的认证文件格式**，思路也不复杂，主要改这几层：

### 1. 先改分类逻辑

看 `classify()` 和 `classify_api_call_response()`：

- 你自己的 provider 会返回什么错误
- 哪些错误应该判成 401 / token 失效
- 哪些错误应该判成额度耗尽 / rate limit / billing 限制

先把这层规则调整对，后面的处理策略才会跟着对。

### 2. 改 account_id / 请求头提取逻辑

看 `choose_account_id()` 和 `direct_probe_auth()`：

- 你的认证文件里账号 ID 在哪
- 你的上游接口需要什么 header
- 是否还需要别的字段而不是 `Chatgpt-Account-Id`

如果不是 OpenAI / Codex 体系，这里通常都要按你自己的接口规范改。

### 3. 改 auth-file 读取 / 写回格式

看 `load_auth_payload_from_path()` 和 `write_auth_payload()`：

如果你的认证文件不是当前这种 JSON 结构，而是别的字段命名，甚至不是 JSON，那这里要先适配。

### 4. 改 refresh 逻辑

看 `refresh_openai_family_tokens()`：

这一段现在是按 OpenAI family 的 refresh 流程写的。
如果你接的是别的 provider，最常见的改法是：

- 替换 token endpoint
- 替换请求参数
- 替换返回字段解析
- 把新的 token 写回成你自己的 auth-file 格式

也就是说，**这一段不是通用标准层，而是当前 provider 适配层**。

### 5. 改 revival 支持范围

看 `run_revival_cycle()`：

现在里面默认只对 `codex`、`openai`、`chatgpt` 做 revival。
如果你要支持别的 provider，需要：

- 把 provider 名加入支持列表
- 保证它有可读本地文件路径
- 保证你前面的 refresh / probe 逻辑已经适配好

### 6. 如果只是“能检测不能 refresh”也可以先接

有些 provider 可能你只能做到：

- 检测可用 / 不可用
- 检测 401
- 检测额度问题

但没法做 refresh。

这种情况也完全可以先接入，只是 revival 部分要降级处理，比如：

- 只禁用
- 到期后只做 probe
- 不做 token refresh
- 或者直接跳过复活机制

### 7. 最实用的适配顺序

如果你要接一个新 provider，我建议按这个顺序来：

1. 先让 `classify()` 正确识别状态
2. 再让 `/api-call` 主动探测可用
3. 再适配 auth-file 读取
4. 最后再补 refresh + revival

这样比较稳，不容易一上来把整套东西改乱。

简单说：

> 这个仓库不是只能支持 codex，但当前“最完整的一套实现”是**以 codex 认证文件为例**来写的。
> 如果换别的认证文件，重点是改 **分类、请求头、文件结构、refresh、revival** 这几层。

## 致谢

感谢 **LinuxDo 社区** 提供交流环境，也感谢 LinuxDo 佬友 [@jingtai123](https://linux.do/t/topic/1810923)，本项目基于其相关脚本思路继续二开整理。

## License

本项目采用 **MIT License**。
详细内容见仓库根目录的 `LICENSE` 文件。
