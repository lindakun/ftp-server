#!/bin/bash
# start.sh - iOS Portal 智能启动器 + mobilerun 运行器
#
# 用法：
#   ./start.sh "你的命令"                    # 自动检测 iOS/Android；两台在线则并发执行
#   ./start.sh --both "你的命令"             # 强制两台并发执行
#   ./start.sh --ios-only "你的命令"         # 只运行 iPhone
#   ./start.sh --android-only "你的命令"     # 只运行 Android
#   ./start.sh "你的命令" --config xxx.yaml  # 传递额外参数
#   ./start.sh --check                       # 仅检查/启动 Portal
set -uo pipefail

PORTAL_HOST="127.0.0.1"
PORTAL_PORT=6643
PORTAL_URL="http://${PORTAL_HOST}:${PORTAL_PORT}"
HEALTH_EP="${PORTAL_URL}/device/date"
IOS_PORTAL_DIR="/Users/linda/code/auto-test/ios-portal"
SCHEME="droidrun-ios-portal"
ONLY_TESTING="Droidrun Server"
MOBILERUN_DIR="/Users/linda/code/auto-test/mobilerun"
DEFAULT_CONFIG="config_multi.yaml"
PORTAL_READY_TIMEOUT=120
IPROXY_READY_TIMEOUT=15
IOS_LOG="/tmp/mobilerun-ios.log"
ANDROID_LOG="/tmp/mobilerun-android.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[$(date +%H:%M:%S)] 信息${NC} $*"; }
ok()   { echo -e "${GREEN}[$(date +%H:%M:%S)] 成功${NC} $*"; }
warn() { echo -e "${YELLOW}[$(date +%H:%M:%S)] 警告${NC} $*"; }
err()  { echo -e "${RED}[$(date +%H:%M:%S)] 错误${NC} $*" >&2; }
check_portal() {
  local resp
  resp=$(curl -sf --connect-timeout 2 --max-time 4 "${HEALTH_EP}" 2>/dev/null) || return 1
  echo "$resp" | grep -q "date" && return 0
  return 1
}

check_portal_ready() {
  check_portal || return 1
  curl -sf --connect-timeout 2 --max-time 10 "${PORTAL_URL}/vision/screenshot" -o /tmp/ios-portal-health-screenshot.png 2>/dev/null || return 1
  curl -sf --connect-timeout 2 --max-time 10 "${PORTAL_URL}/state?timeout=4" -o /tmp/ios-portal-health-state.json 2>/dev/null || return 1
  return 0
}

detect_device() {
  local devices
  if command -v idevice_id &>/dev/null; then
    devices=$(idevice_id -l 2>/dev/null | head -5)
    if [[ -n "$devices" ]]; then echo "$devices" | head -1; return 0; fi
  fi
  if command -v xcrun &>/dev/null; then
    devices=$(xcrun xctrace list devices 2>/dev/null | grep -v Simulator | grep -v Offline | grep -oE "[0-9a-f]{8}-[0-9a-f]{16}" | head -5)
    if [[ -n "$devices" ]]; then echo "$devices" | head -1; return 0; fi
  fi
  return 1
}

detect_android_device() {
  command -v adb &>/dev/null || return 1
  adb devices 2>/dev/null | awk 'NR > 1 && $2 == "device" {print $1; exit}'
}

has_config_arg() {
  local arg
  for arg in "$@"; do [[ "$arg" == "--config" || "$arg" == "-c" ]] && return 0; done
  return 1
}

config_arg_value() {
  local previous=""
  local arg
  for arg in "$@"; do
    if [[ "$previous" == "--config" || "$previous" == "-c" ]]; then
      echo "$arg"
      return 0
    fi
    previous="$arg"
  done
  echo "$DEFAULT_CONFIG"
}

strip_config_args() {
  local skip_next=false
  local arg
  for arg in "$@"; do
    if $skip_next; then
      skip_next=false
      continue
    fi
    if [[ "$arg" == "--config" || "$arg" == "-c" ]]; then
      skip_next=true
      continue
    fi
    printf '%s\n' "$arg"
  done
}

select_model_by_llm() {
  local cmd="$*"
  [[ -z "$cmd" ]] && { echo "lite"; return; }
  python3 "$MOBILERUN_DIR/select_model.py" "$MOBILERUN_DIR/$DEFAULT_CONFIG" "$cmd"
}

make_android_config() {
  local android_serial="$1"
  local model="${2:-lite}"
  shift 2
  local source_config
  source_config=$(config_arg_value "$@")
  local output_config="/tmp/mobilerun-android-${android_serial}.yaml"
  python - "$source_config" "$output_config" "$android_serial" "$model" <<'PY'
import sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
serial = sys.argv[3]
model = sys.argv[4]

text = source.read_text(encoding="utf-8")
lines = text.splitlines()
result = []
i = 0
while i < len(lines):
    line = lines[i]
    result.append(line)
    if line.strip() == "android_emulator: &android_emulator":
        i += 1
        if i < len(lines) and lines[i].lstrip().startswith("serial:"):
            result.append(f"    serial: {serial}")
        else:
            result.append(f"    serial: {serial}")
            continue
    elif line.strip() == "_active_device: &active_device":
        i += 1
        if i < len(lines) and lines[i].lstrip().startswith("<<:"):
            result.append("  <<: *android_emulator")
        else:
            result.append("  <<: *android_emulator")
            continue
    elif line.strip() == "_active_vision_model: &active_vision_model":
        i += 1
        if i < len(lines):
            target = "doubao_turbo" if model == "turbo" else "doubao_lite"
            result.append(f"  <<: *{target}")
        else:
            result.append(f"  <<: *doubao_lite")
            continue
    i += 1

output.write_text("\n".join(result) + "\n", encoding="utf-8")
PY
  echo "$output_config"
}

run_ios_task() {
  cd "$MOBILERUN_DIR"
  if has_config_arg "$@"; then
    mobilerun run "$@" --device "$PORTAL_URL" --ios
  else
    mobilerun run "$@" --config "$DEFAULT_CONFIG" --device "$PORTAL_URL" --ios
  fi
}

run_android_task() {
  local android_serial="$1"
  local model="$2"
  shift 2
  local android_config
  android_config=$(make_android_config "$android_serial" "$model" "$@")
  local filtered_args=()
  while IFS= read -r arg; do
    filtered_args+=("$arg")
  done < <(strip_config_args "$@")
  cd "$MOBILERUN_DIR"
  mobilerun run "${filtered_args[@]}" --config "$android_config" --device "$android_serial"
}

run_parallel_tasks() {
  local android_serial="$1"
  local model="$2"
  shift 2
  log "iOS 与 Android 并发执行中..."
  log "  iOS 日志：${IOS_LOG}"
  log "  Android 日志：${ANDROID_LOG}"
  (run_ios_task "$@" 2>&1 | tee "$IOS_LOG" | sed 's/^/[iOS] /') &
  local ios_pid=$!
  (run_android_task "$android_serial" "$model" "$@" 2>&1 | tee "$ANDROID_LOG" | sed 's/^/[Android] /') &
  local android_pid=$!

  wait "$ios_pid"
  local ios_status=$?
  wait "$android_pid"
  local android_status=$?

  if [[ $ios_status -ne 0 ]]; then
    err "iOS 任务失败（退出码 ${ios_status}），日志尾部："
    tail -40 "$IOS_LOG" >&2
  else
    ok "iOS 任务结束"
  fi

  if [[ $android_status -ne 0 ]]; then
    err "Android 任务失败（退出码 ${android_status}），日志尾部："
    tail -40 "$ANDROID_LOG" >&2
  else
    ok "Android 任务结束"
  fi

  [[ $ios_status -eq 0 && $android_status -eq 0 ]]
}

kill_old_processes() {
  log "清理旧进程..."
  local pids
  pids=$(ps aux | grep '[x]codebuild.*droidrun-ios-portal' | awk '{print $2}')
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null && log "  已杀死 xcodebuild: $pids"; else log "  没有 xcodebuild 在运行"; fi
  pids=$(ps aux | grep '[i]proxy.*6643' | awk '{print $2}')
  if [[ -n "$pids" ]]; then kill $pids 2>/dev/null && log "  已杀死 iproxy: $pids"; else log "  没有 iproxy 在运行"; fi
  sleep 1
}
start_portal() {
  local device_id="$1"
  log "正在启动 iOS Portal（设备：${device_id}）..."
  cd "$IOS_PORTAL_DIR"
  nohup xcodebuild test -project droidrun-ios-portal.xcodeproj -scheme "$SCHEME" -destination "platform=iOS,id=${device_id}" -only-testing "$ONLY_TESTING" -skipMacroValidation -allowProvisioningUpdates > /tmp/ios-portal-build.log 2>&1 &
  local xcbuild_pid=$!
  disown "$xcbuild_pid" 2>/dev/null || true
  log "  xcodebuild PID：${xcbuild_pid}（日志：/tmp/ios-portal-build.log）"
  log "  正在等待 Portal 在设备上启动..."
  local waited=0
  while [[ $waited -lt $PORTAL_READY_TIMEOUT ]]; do
    if ! kill -0 "$xcbuild_pid" 2>/dev/null; then
      if grep -q "Portal server listening on port ${PORTAL_PORT}" /tmp/ios-portal-build.log 2>/dev/null; then break; fi
      err "xcodebuild 已退出。日志尾部："; tail -30 /tmp/ios-portal-build.log; return 1
    fi
    if grep -q "Portal server listening on port ${PORTAL_PORT}" /tmp/ios-portal-build.log 2>/dev/null; then ok "Portal 已在设备上启动"; break; fi
    if grep -qi "locked\|Unlock" /tmp/ios-portal-build.log 2>/dev/null; then err "设备已锁定！请解锁你的 iPhone 后重试。"; return 1; fi
    sleep 2; waited=$((waited + 2)); printf "\r  等待中... %d秒" "$waited"
  done
  echo ""
  if [[ $waited -ge $PORTAL_READY_TIMEOUT ]]; then err "Portal 启动超时（${PORTAL_READY_TIMEOUT}秒）"; tail -30 /tmp/ios-portal-build.log; return 1; fi
  return 0
}

start_iproxy() {
  local device_id="$1"
  log "正在启动 iproxy（${PORTAL_PORT} -> ${device_id}）..."
  nohup iproxy -u "$device_id" -s "$PORTAL_HOST" "${PORTAL_PORT}:${PORTAL_PORT}" > /tmp/ios-portal-iproxy.log 2>&1 &
  local iproxy_pid=$!
  disown "$iproxy_pid" 2>/dev/null || true
  log "  iproxy PID：${iproxy_pid}（日志：/tmp/ios-portal-iproxy.log）"
  local waited=0
  while [[ $waited -lt $IPROXY_READY_TIMEOUT ]]; do
    if check_portal; then ok "iproxy 就绪，Portal 可访问"; return 0; fi
    if ! kill -0 "$iproxy_pid" 2>/dev/null; then err "iproxy 已退出"; cat /tmp/ios-portal-iproxy.log; return 1; fi
    sleep 1; waited=$((waited + 1))
  done
  err "iproxy 就绪超时（${IPROXY_READY_TIMEOUT}秒）"; cat /tmp/ios-portal-iproxy.log; return 1
}
main() {
  local mode="auto"
  case "${1:-}" in
    --both)
      mode="both"; shift ;;
    --ios-only)
      mode="ios"; shift ;;
    --android-only)
      mode="android"; shift ;;
  esac

  echo -e "\n${CYAN}========================================${NC}"
  echo -e "${CYAN}  Mobilerun 多设备启动器${NC}"
  echo -e "${CYAN}========================================${NC}\n"

  local android_serial=""
  android_serial=$(detect_android_device || true)
  if [[ -n "$android_serial" ]]; then
    ok "检测到 Android 设备：${android_serial}"
  else
    warn "未检测到可用 Android 设备"
  fi

  local need_ios=false
  local need_android=false
  case "$mode" in
    ios) need_ios=true ;;
    android) need_android=true ;;
    both) need_ios=true; need_android=true ;;
    auto)
      if [[ -n "$android_serial" ]]; then
        need_ios=true
        need_android=true
      else
        need_ios=true
      fi
      ;;
  esac

  if $need_ios; then
    if check_portal_ready; then
      ok "Portal 已在运行且深度验证通过（${PORTAL_URL}）"
    else
      warn "Portal 未就绪或深度验证失败，正在启动..."
      kill_old_processes
      local device_id
      device_id=$(detect_device) || { err "未检测到 iOS 设备！请检查 USB 连接和信任授权。"; exit 1; }
      ok "检测到 iOS 设备：${device_id}"
      start_portal "$device_id" || exit 1
      start_iproxy "$device_id" || exit 1
      if check_portal_ready; then ok "Portal 深度验证通过！"; else err "Portal 深度验证失败：/state 或截图接口不可用"; exit 1; fi
    fi
  fi

  if [[ "${1:-}" == "--check" ]]; then echo ""; ok "Portal 已就绪，现在可以运行 mobilerun 了"; exit 0; fi

  if [[ $# -eq 0 ]]; then echo ""; ok "设备检查完成。没有传入命令。"; echo "  用法：$0 [--both|--ios-only|--android-only] '你的命令' [--config xxx.yaml]"; exit 0; fi

  if $need_android && [[ -z "$android_serial" ]]; then
    err "需要运行 Android，但 adb 没有检测到可用设备。"
    exit 1
  fi

  echo ""
  log "用 longcat 分析任务复杂度，选择视觉模型..."
  local vision_model
  vision_model=$(select_model_by_llm "$@")
  log "  视觉模型：${vision_model}（turbo=强视觉 / lite=轻量快）"
  echo ""
  log "正在运行 mobilerun..."
  echo -e "${CYAN}----------------------------------------${NC}\n"

  if $need_ios && $need_android; then
    run_parallel_tasks "$android_serial" "$vision_model" "$@" || exit 1
  elif $need_ios; then
    run_ios_task "$@"
  else
    run_android_task "$android_serial" "$vision_model" "$@"
  fi
}

main "$@"
