#!/bin/bash

# ================= 配置变量 =================
INSTALL_DIR="/opt/CLIProxyAPI-cleaner"
LOG_FILE="/root/CLIProxyAPI-cleaner.log"
STATE_FILE="/root/CLIProxyAPI-cleaner-state.json"
SERVICE_FILES=(
    "CLIProxyAPI-cleaner.service"
    "CLIProxyAPI-cleaner-web.service"
    "CLIProxyAPI-cleaner-retention.service"
    "CLIProxyAPI-cleaner-retention.timer"
)

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # 无颜色

# ================= 权限检查 =================
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}错误: 必须以 root 权限运行此脚本。${NC}"
   exit 1
fi

install() {
    echo -e "${CYAN}================================================${NC}"
    echo -e "${CYAN}  开始安装 CLIProxyAPI-cleaner (通用交互版) ${NC}"
    echo -e "${CYAN}================================================${NC}"

    # 1. 检查 Python 版本
    PYTHON_VER=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    if [[ $(echo "$PYTHON_VER < 3.10" | bc -l) -eq 1 ]]; then
        echo -e "${RED}错误: 需要 Python 3.10+，当前版本: $PYTHON_VER${NC}"
        exit 1
    fi

    # 2. 准备目录
    echo -e "${GREEN}[1/5] 准备安装目录与拷贝文件...${NC}"
    mkdir -p "$INSTALL_DIR"
    cp -r ./* "$INSTALL_DIR/"

    # 3. 修补 app.py (解决 HTTP 登录卡死/401 问题)
    echo -e "${GREEN}[2/5] 修补后端 Cookie 安全策略...${NC}"
    if [ -f "$INSTALL_DIR/app.py" ]; then
        # 使用更强大的正则替换：匹配整行 COOKIE_SECURE 赋值，并替换为 False
        sed -i -E 's/^[[:space:]]*COOKIE_SECURE[[:space:]]*=.*/COOKIE_SECURE = False/g' "$INSTALL_DIR/app.py"
        echo -e "${YELLOW}  -> 已成功将 COOKIE_SECURE 强制修改为 False，允许 HTTP 访问。${NC}"
    else
        echo -e "${RED}未找到 app.py，请确保你在源码目录下执行此脚本！${NC}"
        exit 1
    fi

    # 4. 交互式收集隐私变量
    echo -e "${GREEN}[3/5] 配置关键参数...${NC}"
    
    # 收集 base_url
    read -p "请输入管理面板地址 (base_url, 例如 http://10.x.x.x:8317/management.html): " INPUT_BASE_URL
    while [[ -z "$INPUT_BASE_URL" ]]; do
        echo -e "${RED}地址不能为空，请重新输入。${NC}"
        read -p "请输入管理面板地址 (base_url): " INPUT_BASE_URL
    done

    # 收集 management_key
    read -p "请输入管理密钥 (management_key): " INPUT_MANAGEMENT_KEY
    while [[ -z "$INPUT_MANAGEMENT_KEY" ]]; do
        echo -e "${RED}密钥不能为空，请重新输入。${NC}"
        read -p "请输入管理密钥 (management_key): " INPUT_MANAGEMENT_KEY
    done

    # 收集控制台密码
    read -s -p "请输入你要设置的 Web 控制台登录密码: " USER_PASS
    echo ""
    read -s -p "请再次输入以确认: " USER_PASS2
    echo ""
    
    if [ "$USER_PASS" != "$USER_PASS2" ]; then
        echo -e "${RED}两次密码不一致，安装终止。${NC}"
        exit 1
    fi

    # 生成密码哈希
    export TEMP_PASS="$USER_PASS"
    read -r SALT HASH <<< $(python3 -c "
import os, hashlib
p = os.environ.get('TEMP_PASS')
s = os.urandom(16).hex()
h = hashlib.pbkdf2_hmac('sha256', p.encode(), bytes.fromhex(s), 260000).hex()
print(f'{s} {h}')
")
    unset TEMP_PASS

    # 动态生成配置文件
    cat << EOF > "$INSTALL_DIR/web_config.json"
{
  "listen_host": "0.0.0.0",
  "listen_port": 28717,
  "allowed_hosts": ["*", "127.0.0.1", "localhost"],
  "cleaner_path": "$INSTALL_DIR/CLIProxyAPI-cleaner.py",
  "state_file": "$STATE_FILE",
  "base_url": "$INPUT_BASE_URL",
  "management_key": "$INPUT_MANAGEMENT_KEY",
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
  "retention_keep_reports": 200,
  "retention_report_max_age_days": 7,
  "retention_backup_max_age_days": 14,
  "retention_log_max_size_mb": 50,
  "password_salt": "$SALT",
  "password_hash": "$HASH"
}
EOF
    echo -e "${YELLOW}  -> 配置已生成并安全写入。${NC}"

    # 5. 配置 Systemd
    echo -e "${GREEN}[4/5] 部署并启动 Systemd 服务...${NC}"
    for service in "${SERVICE_FILES[@]}"; do
        if [ -f "$INSTALL_DIR/$service" ]; then
            cp "$INSTALL_DIR/$service" "/etc/systemd/system/"
        fi
    done

    systemctl daemon-reload
    systemctl enable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service CLIProxyAPI-cleaner-retention.timer
    systemctl restart CLIProxyAPI-cleaner-web.service
    systemctl restart CLIProxyAPI-cleaner.service
    systemctl restart CLIProxyAPI-cleaner-retention.timer

    echo -e "${GREEN}[5/5] 服务状态检查...${NC}"
    systemctl is-active --quiet CLIProxyAPI-cleaner-web.service && echo -e "  -> Web 控制台: ${GREEN}运行中${NC}" || echo -e "  -> Web 控制台: ${RED}失败${NC}"
    systemctl is-active --quiet CLIProxyAPI-cleaner.service && echo -e "  -> 清理主程序: ${GREEN}运行中${NC}" || echo -e "  -> 清理主程序: ${RED}失败${NC}"

    echo -e "${CYAN}================================================${NC}"
    echo -e "${GREEN}安装彻底完成！${NC}"
    echo -e "请在浏览器访问: ${YELLOW}http://你的服务器IP:28717/CLIProxyAPI-cleaner/${NC}"
    echo -e "日志监控命令: ${YELLOW}tail -f $LOG_FILE${NC}"
    echo -e "${CYAN}================================================${NC}"
}

uninstall() {
    echo -e "${RED}================================================${NC}"
    echo -e "${RED}  准备彻底卸载 CLIProxyAPI-cleaner ${NC}"
    echo -e "${RED}================================================${NC}"
    read -p "危险: 将删除所有程序文件、日志和配置文件。确定吗？(y/n): " CONFIRM
    if [[ "$CONFIRM" != "y" ]]; then
        echo -e "${YELLOW}已取消卸载。${NC}"
        exit 0
    fi

    echo -e "${YELLOW}正在停止并禁用服务...${NC}"
    systemctl stop CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service CLIProxyAPI-cleaner-retention.timer CLIProxyAPI-cleaner-retention.service
    systemctl disable CLIProxyAPI-cleaner.service CLIProxyAPI-cleaner-web.service CLIProxyAPI-cleaner-retention.timer CLIProxyAPI-cleaner-retention.service

    echo -e "${YELLOW}清理 Systemd 配置文件...${NC}"
    for service in "${SERVICE_FILES[@]}"; do
        rm -f "/etc/systemd/system/$service"
    done
    systemctl daemon-reload
    systemctl reset-failed

    echo -e "${YELLOW}删除安装目录与数据文件...${NC}"
    rm -rf "$INSTALL_DIR"
    rm -f "$LOG_FILE"
    rm -f "$STATE_FILE"

    echo -e "${GREEN}卸载干净无残留！${NC}"
}

case "$1" in
    install)
        install
        ;;
    uninstall)
        uninstall
        ;;
    *)
        echo -e "用法: $0 {${GREEN}install${NC}|${RED}uninstall${NC}}"
        exit 1
        ;;
esac
