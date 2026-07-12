# Windows 迁移计划

## 背景
mobilerun 是 GitHub 开源仓库，Windows 上直接 clone + pip install 即可。
本次迁移只需处理达叔在 macOS 上定制的 3 个文件，并为 Windows 环境做适配。

## 需要迁移的文件

| 源文件（macOS） | Windows 适配 | 说明 |
|---|---|---|
| `mobilerun/config_multi.yaml` | 直接复制，改一行 | `_active_device` 从 `*ios_lams` 改为 `*android_emulator` |
| `mobilerun/select_model.py` | 直接复制，不改 | 纯 Python，跨平台 |
| `mobilerun/start.sh` | 重写为 `start.ps1` | bash → PowerShell，砍掉所有 iOS 逻辑 |

## 产出物

1. **`install_windows.md`** — 一份完整的 Windows 安装指引，包含：
   - Python 3.11+ 安装
   - adb 安装与配置
   - mobilerun 克隆与 pip install
   - 个性化文件放置到对应位置
   - 运行示例

2. **`mobilerun/start.ps1`** — Windows 版 PowerShell 启动脚本
   - 纯 Android 模式（无 iOS）
   - 保持 `select_model_by_llm()` 模型选择
   - 保持 `make_android_config()` 动态配置生成
   - 保持 `run_android_task()` 任务执行
   - 用法：`.\start.ps1 "命令"`
   - 日志输出用 Windows 临时目录 `$env:TEMP`

3. **`mobilerun/config_multi_windows.yaml`** — Windows 专用配置
   - 基于 config_multi.yaml，`_active_device` 默认指向 `*android_emulator`
   - 其他配置不变

## start.ps1 vs start.sh 差异

| 对比项 | start.sh (macOS) | start.ps1 (Windows) |
|---|---|---|
| iOS Portal | ✅ 有（~200行） | ❌ 移除 |
| Android | ✅ 有 | ✅ 保留 |
| 模型选择 | ✅ longcat | ✅ longcat |
| 并发双端 | ✅ iOS+Android | ❌ 不需要（只有 Android） |
| 日志目录 | `/tmp/` | `$env:TEMP\` |
| Python 命令 | `python3` | `python` |
| 颜色输出 | `\033[...` | `Write-Host -ForegroundColor` |

## 安装指引大纲

```
install_windows.md:
├── 1. 环境准备
│   ├── Python 3.11+ 安装
│   ├── adb 安装与 PATH 配置
│   └── 手机 USB 调试开启
├── 2. 安装 mobilerun
│   ├── git clone
│   └── pip install -e .
├── 3. 放置个性化文件
│   ├── config_multi_windows.yaml → mobilerun/
│   ├── select_model.py → mobilerun/
│   └── start.ps1 → mobilerun/
├── 4. 验证环境
│   └── adb devices / mobilerun doctor
├── 5. 运行示例
│   └── .\start.ps1 "打开b站给首页视频点个赞"
```

## 执行步骤

1. 创建 `mobilerun/start.ps1`（PowerShell 版启动脚本）
2. 创建 `mobilerun/config_multi_windows.yaml`（Windows 版配置）
3. 创建 `mobilerun/install_windows.md`（安装指引文档）
4. 把 `select_model.py` 复制或确认它已在 mobilerun 目录下
5. 验证所有文件一致性
