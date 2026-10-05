#!/usr/bin/env bash
#
# 在服务器上安装 / 更新「局域网文件共享（网页版）」服务。
# 适用于 Ubuntu 22.04 / 24.04，需要 sudo。
#
# 用法：
#   sudo bash install_remote.sh
#
# 这个脚本做四件事（可重复执行，幂等）：
#   1. 建系统用户 fileshare 与数据目录 /var/lib/fileshare
#   2. 同步代码到 /opt/fileshare（已有仓库则 pull）
#   3. 安装配置 /etc/fileshare/env（保留自定义配置，升级旧默认上传上限）
#   4. 安装 systemd 单元并启动
#
set -euo pipefail

APP_USER=fileshare
APP_DIR=/opt/fileshare
DATA_ROOT=/var/lib/fileshare
CONF_DIR=/etc/fileshare
REPO_URL="${REPO_URL:-https://github.com/lindakun/ftp-server.git}"
GIT_USER="${GIT_USER:-ubuntu}"

if [ "$(id -u)" -ne 0 ]; then
  echo "[错误] 需要 root 权限，请用：sudo bash install_remote.sh" >&2
  exit 1
fi

if ! id "$GIT_USER" >/dev/null 2>&1; then
  echo "[错误] 找不到用于 git 操作的用户：$GIT_USER" >&2
  echo "       可用 GIT_USER=<用户> sudo -E bash install_remote.sh 指定" >&2
  exit 1
fi
GIT_HOME=$(getent passwd "$GIT_USER" | cut -d: -f6)

echo "==> 1/5 创建系统用户与数据目录"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --shell /usr/sbin/nologin --home-dir "$DATA_ROOT" "$APP_USER"
  echo "    已创建用户 $APP_USER"
else
  echo "    用户 $APP_USER 已存在，跳过"
fi
install -d -m 0755 "$DATA_ROOT"
install -d -m 0755 -o "$APP_USER" -g "$APP_USER" "$DATA_ROOT/shared"
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "$DATA_ROOT/data"

echo "==> 2/5 同步代码到 $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  runuser -u "$GIT_USER" -- env HOME="$GIT_HOME" git -C "$APP_DIR" pull --ff-only
  echo "    已拉取最新代码"
else
  install -d -m 0755 -o "$GIT_USER" -g "$GIT_USER" "$APP_DIR"
  runuser -u "$GIT_USER" -- env HOME="$GIT_HOME" git clone "$REPO_URL" "$APP_DIR"
  echo "    已克隆仓库"
fi

echo "==> 3/5 安装配置 $CONF_DIR/env"
install -d -m 0755 "$CONF_DIR"
if [ -f "$CONF_DIR/env" ]; then
  # 将旧的默认 2GiB 上限升级为 4GiB，其他自定义值保持不变。
  sed -i 's/^MAX_UPLOAD_MB=2048$/MAX_UPLOAD_MB=4096/' "$CONF_DIR/env"
  echo "    保留现有配置，旧默认上传上限升级到 4096MB"
else
  install -m 0640 -o root -g root "$APP_DIR/deploy/env.example" "$CONF_DIR/env"
  echo "    已从 env.example 生成默认配置"
fi

echo "==> 4/5 安装 systemd 单元"
install -m 0644 "$APP_DIR/deploy/fileshare.service" /etc/systemd/system/fileshare.service
systemctl daemon-reload

echo "==> 5/5 启动服务"
systemctl enable --now fileshare
systemctl restart fileshare
sleep 2
systemctl --no-pager --lines=0 status fileshare || true

PORT=$(awk -F= '/^HTTP_PORT=/{print $2}' "$CONF_DIR/env" | tr -d ' \r')
PORT=${PORT:-18080}
echo
echo "================ 部署完成 ================"
echo "  监听     : 127.0.0.1:$PORT（仅本机，未开公网）"
echo "  共享目录 : $DATA_ROOT/shared"
echo "  日志     : journalctl -u fileshare -f"
echo "  重启     : sudo systemctl restart fileshare"
echo "  停止     : sudo systemctl stop fileshare"
echo "  卸载     : sudo systemctl disable --now fileshare"
echo
echo "  本机开隧道后访问："
echo "    ssh -N -L $PORT:127.0.0.1:$PORT <服务器别名>"
echo "    然后浏览器打开 http://127.0.0.1:$PORT"
echo "=========================================="
