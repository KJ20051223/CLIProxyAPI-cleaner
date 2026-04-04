# CLIProxyAPI-cleaner

中文 | [English](README_EN.md)

`CLIProxyAPI-cleaner` 是一个“**自动清理脚本 + Web 控制台**”一体化项目，用来管理和清理 CLIProxyAPI / auth-file 相关账号状态。

仓库默认首页是中文说明；如果你想看英文版，可以直接点上面的 **English**。

## 这个仓库包含什么

- `CLIProxyAPI-cleaner.py`：真正执行检测、禁用、删除、refresh、复活探测的主脚本
- `app.py`：轻量 Web 后端，负责登录、状态查询、保存配置、控制 systemd、查看报告
- `common.py`：配置加载、校验、命令拼装
- `run_cleaner.py`：读取 `web_config.json` 并按当前配置启动 cleaner
- `CLIProxyAPI-cleaner.service`：后台清理服务
- `CLIProxyAPI-cleaner-web.service`：控制台服务
- `static/`：前端页面
- `web_config.example.json`：公开版示例配置

## 能做什么

- 参数填写与保存
- 一键启动 / 停止 / 重启 cleaner
- 一键重启 Web 控制台后端
- 一键执行 dry-run
- 查看 cleaner / web 日志
- 查看最近报告（默认前 5 个）
- 登录限流、Host 白名单、Cookie 安全属性

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
├── CLIProxyAPI-cleaner.service
├── CLIProxyAPI-cleaner-web.service
├── web_config.example.json
├── static/
│   ├── index.html
│   ├── app.js
│   └── styles.css
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

## 5）安装 systemd 服务

```bash
cp CLIProxyAPI-cleaner.service /etc/systemd/system/CLIProxyAPI-cleaner.service
cp CLIProxyAPI-cleaner-web.service /etc/systemd/system/CLIProxyAPI-cleaner-web.service
systemctl daemon-reload
systemctl enable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service
```

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
```

如果更新中改了 service 文件，记得再执行：

```bash
systemctl daemon-reload
```

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

## License

本项目采用 **MIT License**。
详细内容见仓库根目录的 `LICENSE` 文件。
