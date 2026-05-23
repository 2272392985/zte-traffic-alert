# 中兴随身 WiFi 流量提醒

一个跨平台桌面应用，用来读取中兴随身 WiFi 管理接口的月流量统计，并在剩余流量低于阈值时提醒或自动断开蜂窝网络。

默认设备页面：

```text
http://192.168.0.1/index.html#traffic_alert
```

## 当前架构

新版主线已经重构为类似 cockpit-tools 的 Tauri 桌面应用：

```text
React + TypeScript + Vite 前端
        ↓
Tauri 2 invoke 命令
        ↓
Rust 原生后端
        ↓
中兴路由器 goform 接口
```

保留 `zte_traffic_alert/` 里的 Python 版本作为备用实现，但后续功能会优先放到 Tauri 版。

## 功能

- 桌面仪表盘显示已用流量、剩余流量和触发状态。
- 支持配置套餐总量和“剩余多少 GB 自动断网”。
- 支持 `dry_run` 测试模式和 `router_disconnect` 真实断网模式。
- Tauri 版由 Rust 后台线程执行监控，关闭窗口时隐藏到系统托盘，不退出应用。
- 托盘菜单支持重新显示窗口和退出应用。
- 读取接口和断网接口均使用中兴 Web 管理后台的 `/goform` API。
- macOS / Windows / Linux 可通过 Tauri 打包为原生桌面应用。

## 开发运行

先安装：

- Node.js
- Rust/Cargo
- 平台原生构建工具：macOS 需要 Xcode Command Line Tools，Windows 需要 Microsoft C++ Build Tools/WebView2

然后运行：

```bash
npm install
npm run tauri:dev
```

只运行前端预览：

```bash
npm run dev
```

## 打包

macOS：

```bash
scripts/build_tauri_macos.sh
```

产物目录：

```text
src-tauri/target/release/bundle
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_tauri_windows.ps1
```

产物目录：

```text
src-tauri\target\release\bundle
```

注意：Tauri 一般不做可靠跨平台交叉打包。macOS 包请在 macOS 上构建，Windows 包请在 Windows 上构建。

## 配置

Tauri 版会在用户配置目录创建：

```text
ZTE Traffic Alert/config.json
```

默认配置核心字段：

```json
{
  "router": {
    "base_url": "http://192.168.0.1",
    "admin_password": ""
  },
  "traffic": {
    "plan_gb": 241,
    "unit": "GiB",
    "disconnect_when_remaining_gb_lte": 2
  },
  "action": {
    "mode": "dry_run",
    "repeat_disconnect": false
  }
}
```

`mode` 说明：

- `dry_run`：只显示/记录触发状态，不断网。
- `router_disconnect`：达到阈值后调用路由器断网接口。

桌面运行逻辑：

- “刷新流量”只读取状态，不会自动断网。
- “启动监控”会让 Rust 后台线程按轮询间隔持续检查。
- 达到阈值时，后台线程根据 `mode` 决定记录或断网。
- 关闭窗口会隐藏到托盘；要完全退出，请用托盘菜单的“退出”。

## 旧 Python 备用版

命令行检查：

```bash
python3 -m zte_traffic_alert --config config.json once
```

Tkinter 旧界面：

```bash
python3 -m zte_traffic_alert --config config.json gui
```

PyInstaller 旧打包脚本仍保留：

```bash
scripts/build_macos_app.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_exe.ps1
```
