# 中兴随身 WiFi 流量提醒/自动断网

一个轻量化本地服务，用来定时读取中兴随身 WiFi 管理页的流量统计，并在套餐剩余流量低于指定阈值时自动执行动作。

默认路由器地址：

```text
http://192.168.0.1/index.html#traffic_alert
```

## 功能

- 定时读取中兴 Web 管理接口的月流量统计。
- 按「套餐总量 - 已用流量」计算剩余流量。
- 剩余流量低于阈值时执行动作：
  - `dry_run`：只记录日志，不断网。
  - `router_disconnect`：调用路由器断开联网接口。
  - `local_command`：执行你自定义的本机命令。
- 支持 macOS `launchd` 常驻。
- 支持 Windows 计划任务常驻。
- 无第三方 Python 依赖。

## 快速开始

1. 复制配置：

```bash
cp config.example.json config.json
```

2. 修改 `config.json`：

```json
{
  "traffic": {
    "plan_gb": 241,
    "disconnect_when_remaining_gb_lte": 2
  },
  "action": {
    "mode": "dry_run"
  }
}
```

先保持 `dry_run`，确认读取结果正确后，再改成：

```json
{
  "action": {
    "mode": "router_disconnect"
  }
}
```

3. 诊断读取接口：

```bash
python3 -m zte_traffic_alert --config config.json diagnose
```

4. 单次检查：

```bash
python3 -m zte_traffic_alert --config config.json once
```

5. 前台常驻：

```bash
python3 -m zte_traffic_alert --config config.json run
```

## macOS 安装为轻量服务

```bash
chmod +x scripts/install_macos.sh scripts/uninstall_macos.sh
scripts/install_macos.sh
```

卸载：

```bash
scripts/uninstall_macos.sh
```

日志默认写到项目目录的 `zte_traffic_alert.log`。

## Windows 安装为计划任务

在 PowerShell 中执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows.ps1
```

卸载：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_windows.ps1
```

## 重要配置

`router.base_url`

路由器管理页地址，默认 `http://192.168.0.1`。

`router.admin_password`

如果你的设备调用断网接口需要登录，把后台管理密码填在这里。部分中兴设备不登录也可以读取流量，但断网通常需要登录。

`traffic.plan_gb`

套餐总流量。你的设备页面显示 `236.11GB / 241GB`，这里就填 `241`。

`traffic.disconnect_when_remaining_gb_lte`

剩余多少 GB 以内触发动作。例如填 `2` 表示剩余小于等于 2GB 时断网。

`traffic.unit`

计算单位。你的设备页面把 1024 进制显示成 `GB`，所以默认使用 `GiB`，这样程序结果会和页面上的 `236.11GB` 一致。

`service.poll_interval_seconds`

轮询间隔，默认 300 秒。

`action.mode`

动作模式。建议先用 `dry_run` 跑一天确认统计准确。

`action.repeat_disconnect`

默认 `false`，触发一次后不重复执行断网。新账期开始或手动删除 state 文件后可再次触发。

## 如果诊断读取不到流量

不同中兴固件的字段名可能略有不同。请打开：

```text
http://192.168.0.1/index.html#traffic_alert
```

然后在浏览器开发者工具的 Network 面板里刷新页面，查找请求：

```text
/goform/goform_get_cmd_process
```

把返回 JSON 里的流量字段名填到 `traffic.rx_field` 和 `traffic.tx_field`。

常见字段：

- `monthly_rx_bytes`
- `monthly_tx_bytes`
- `total_rx_bytes`
- `total_tx_bytes`
