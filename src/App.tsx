import {
  Activity,
  AlertTriangle,
  Bell,
  CheckCircle2,
  CircleStop,
  Gauge,
  PlugZap,
  Power,
  RefreshCw,
  Save,
  Settings,
  ShieldCheck,
  Wifi,
} from "lucide-react";
import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useEffect, useMemo, useRef, useState } from "react";

type ActionMode = "dry_run" | "router_disconnect";

type AppConfig = {
  router: {
    base_url: string;
    admin_password: string;
    request_timeout_seconds: number;
    disconnect_goform_ids: string[];
  };
  traffic: {
    plan_gb: number;
    unit: "GiB" | "GB";
    disconnect_when_remaining_gb_lte: number;
    rx_field: string;
    tx_field: string;
    counter_mode: "monthly" | "total";
  };
  service: {
    poll_interval_seconds: number;
  };
  action: {
    mode: ActionMode;
    repeat_disconnect: boolean;
  };
};

type TrafficStatus = {
  used_bytes: number;
  remaining_bytes: number;
  triggered: boolean;
  action: string;
  rx_field: string;
  tx_field: string;
  checked_at: string;
};

type MonitorInfo = {
  running: boolean;
  last_status: TrafficStatus | null;
  last_error: string;
};

const emptyStatus: TrafficStatus = {
  used_bytes: 0,
  remaining_bytes: 0,
  triggered: false,
  action: "",
  rx_field: "",
  tx_field: "",
  checked_at: "",
};

const defaultConfig: AppConfig = {
  router: {
    base_url: "http://192.168.0.1",
    admin_password: "",
    request_timeout_seconds: 8,
    disconnect_goform_ids: ["DISCONNECT_NETWORK", "DISCONNECT"],
  },
  traffic: {
    plan_gb: 241,
    unit: "GiB",
    disconnect_when_remaining_gb_lte: 2,
    rx_field: "",
    tx_field: "",
    counter_mode: "monthly",
  },
  service: {
    poll_interval_seconds: 300,
  },
  action: {
    mode: "dry_run",
    repeat_disconnect: false,
  },
};

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

const isTauriRuntime = () => typeof window.__TAURI_INTERNALS__ !== "undefined";

async function invokeCommand<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauriRuntime()) {
    return tauriInvoke<T>(command, args);
  }

  if (command === "load_config") {
    const saved = window.localStorage.getItem("zte-traffic-alert-config");
    return (saved ? JSON.parse(saved) : defaultConfig) as T;
  }

  if (command === "save_config") {
    window.localStorage.setItem("zte-traffic-alert-config", JSON.stringify(args?.config));
    return args?.config as T;
  }

  if (command === "check_traffic") {
    const config = JSON.parse(
      window.localStorage.getItem("zte-traffic-alert-config") || JSON.stringify(defaultConfig),
    ) as AppConfig;
    const usedBytes = 236.18 * 1024 ** 3;
    const remainingBytes = Math.max(config.traffic.plan_gb * 1024 ** 3 - usedBytes, 0);
    return {
      used_bytes: usedBytes,
      remaining_bytes: remainingBytes,
      triggered:
        remainingBytes <= config.traffic.disconnect_when_remaining_gb_lte * 1024 ** 3,
      action: "",
      rx_field: "monthly_rx_bytes",
      tx_field: "monthly_tx_bytes",
      checked_at: new Date().toLocaleString(),
    } as T;
  }

  if (command === "disconnect_router") {
    return "浏览器预览模式：未真正调用路由器断网接口" as T;
  }

  if (command === "start_monitor") {
    return {
      running: true,
      last_status: null,
      last_error: "",
    } as T;
  }

  if (command === "stop_monitor") {
    return {
      running: false,
      last_status: null,
      last_error: "",
    } as T;
  }

  if (command === "monitor_status") {
    return {
      running: false,
      last_status: null,
      last_error: "",
    } as T;
  }

  throw new Error(`浏览器预览模式不支持命令：${command}`);
}

function formatTraffic(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function App() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [status, setStatus] = useState<TrafficStatus>(emptyStatus);
  const [busy, setBusy] = useState(false);
  const [monitoring, setMonitoring] = useState(false);
  const [message, setMessage] = useState("正在载入配置...");
  const timerRef = useRef<number | null>(null);

  const remainingPercent = useMemo(() => {
    if (!config) return 0;
    const plan = config.traffic.plan_gb * 1024 ** 3;
    return Math.max(0, Math.min(100, (status.remaining_bytes / plan) * 100));
  }, [config, status.remaining_bytes]);

  const usedPercent = 100 - remainingPercent;

  useEffect(() => {
    invokeCommand<AppConfig>("load_config")
      .then((next) => {
        setConfig(next);
        setMessage(isTauriRuntime() ? "配置已载入" : "浏览器预览模式");
      })
      .catch((error) => setMessage(String(error)));
  }, []);

  useEffect(() => {
    if (!isTauriRuntime()) return;

    let unlistenStatus: (() => void) | undefined;
    let unlistenError: (() => void) | undefined;
    void listen<TrafficStatus>("traffic-status", (event) => {
      setStatus(event.payload);
      setMessage(event.payload.triggered ? "后台监控已触发阈值" : "后台监控已刷新");
    }).then((unlisten) => {
      unlistenStatus = unlisten;
    });
    void listen<string>("traffic-error", (event) => {
      setMessage(`后台监控失败：${event.payload}`);
    }).then((unlisten) => {
      unlistenError = unlisten;
    });
    void invokeCommand<MonitorInfo>("monitor_status").then((info) => {
      setMonitoring(info.running);
      if (info.last_status) setStatus(info.last_status);
      if (info.last_error) setMessage(`后台监控失败：${info.last_error}`);
    });

    return () => {
      unlistenStatus?.();
      unlistenError?.();
    };
  }, []);

  useEffect(() => {
    if (isTauriRuntime() || !monitoring || !config) return;

    const interval = Math.max(config.service.poll_interval_seconds, 10) * 1000;
    timerRef.current = window.setInterval(() => {
      void refreshTraffic();
    }, interval);
    return () => {
      if (timerRef.current) {
        window.clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [monitoring, config]);

  async function toggleMonitor() {
    if (!config) return;
    if (!isTauriRuntime()) {
      setMonitoring((value) => !value);
      setMessage(monitoring ? "浏览器预览监控已停止" : "浏览器预览监控已启动");
      return;
    }

    setBusy(true);
    try {
      const saved = await invokeCommand<AppConfig>("save_config", { config });
      setConfig(saved);
      const info = await invokeCommand<MonitorInfo>(
        monitoring ? "stop_monitor" : "start_monitor",
      );
      setMonitoring(info.running);
      if (info.last_status) setStatus(info.last_status);
      setMessage(info.running ? "后台监控已启动，可关闭窗口隐藏到托盘" : "后台监控已停止");
    } catch (error) {
      setMessage(`监控切换失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveConfig(nextConfig = config) {
    if (!nextConfig) return;
    setBusy(true);
    try {
      const saved = await invokeCommand<AppConfig>("save_config", { config: nextConfig });
      setConfig(saved);
      setMessage("配置已保存");
    } catch (error) {
      setMessage(`保存失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function refreshTraffic() {
    if (!config) return;
    setBusy(true);
    try {
      const saved = await invokeCommand<AppConfig>("save_config", { config });
      setConfig(saved);
      const next = await invokeCommand<TrafficStatus>("check_traffic");
      setStatus(next);
      setMessage(next.triggered ? "已达到断网阈值" : "流量状态已刷新");
    } catch (error) {
      setMessage(`刷新失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function disconnectNow() {
    if (!window.confirm("要立即调用随身 WiFi 的断网接口吗？")) return;
    setBusy(true);
    try {
      const result = await invokeCommand<string>("disconnect_router");
      setStatus((current) => ({ ...current, action: "router_disconnect" }));
      setMessage(result);
    } catch (error) {
      setMessage(`断网失败：${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function updateConfig(mutator: (draft: AppConfig) => void) {
    setConfig((current) => {
      if (!current) return current;
      const draft = structuredClone(current);
      mutator(draft);
      return draft;
    });
  }

  if (!config) {
    return (
      <main className="app-shell loading">
        <div className="spinner" />
        <p>{message}</p>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">ZTE Traffic Alert</p>
          <h1>中兴随身 WiFi 流量提醒</h1>
        </div>
        <div className={`status-pill ${monitoring ? "online" : ""}`}>
          <Activity size={16} />
          {monitoring ? "监控运行中" : "监控未启动"}
        </div>
      </header>

      <section className="dashboard">
        <div className="metric primary">
          <div className="metric-title">
            <Gauge size={18} />
            剩余流量
          </div>
          <strong>{formatTraffic(status.remaining_bytes)}</strong>
          <span>阈值 {config.traffic.disconnect_when_remaining_gb_lte} GB</span>
        </div>
        <div className="metric">
          <div className="metric-title">
            <Wifi size={18} />
            已用流量
          </div>
          <strong>{formatTraffic(status.used_bytes)}</strong>
          <span>套餐 {config.traffic.plan_gb} GB</span>
        </div>
        <div className="metric">
          <div className="metric-title">
            <ShieldCheck size={18} />
            动作状态
          </div>
          <strong>{status.triggered ? "已触发" : "正常"}</strong>
          <span>{status.action || "未执行"}</span>
        </div>
      </section>

      <section className="progress-panel">
        <div className="progress-header">
          <span>本月流量使用进度</span>
          <b>{usedPercent.toFixed(1)}%</b>
        </div>
        <div className="traffic-bar">
          <div style={{ width: `${usedPercent}%` }} />
        </div>
        <div className="progress-footer">
          <span>RX: {status.rx_field || "-"}</span>
          <span>TX: {status.tx_field || "-"}</span>
          <span>{status.checked_at || "尚未检查"}</span>
        </div>
      </section>

      <section className="workspace">
        <div className="panel">
          <div className="panel-title">
            <Settings size={18} />
            连接与套餐
          </div>
          <label>
            路由器地址
            <input
              value={config.router.base_url}
              onChange={(event) =>
                updateConfig((draft) => {
                  draft.router.base_url = event.target.value;
                })
              }
            />
          </label>
          <label>
            后台密码
            <input
              type="password"
              value={config.router.admin_password}
              onChange={(event) =>
                updateConfig((draft) => {
                  draft.router.admin_password = event.target.value;
                })
              }
            />
          </label>
          <div className="grid-two">
            <label>
              套餐总量
              <input
                type="number"
                min="1"
                value={config.traffic.plan_gb}
                onChange={(event) =>
                  updateConfig((draft) => {
                    draft.traffic.plan_gb = Number(event.target.value);
                  })
                }
              />
            </label>
            <label>
              断网阈值
              <input
                type="number"
                min="0"
                step="0.1"
                value={config.traffic.disconnect_when_remaining_gb_lte}
                onChange={(event) =>
                  updateConfig((draft) => {
                    draft.traffic.disconnect_when_remaining_gb_lte = Number(event.target.value);
                  })
                }
              />
            </label>
          </div>
        </div>

        <div className="panel">
          <div className="panel-title">
            <Bell size={18} />
            监控动作
          </div>
          <label>
            动作模式
            <select
              value={config.action.mode}
              onChange={(event) =>
                updateConfig((draft) => {
                  draft.action.mode = event.target.value as ActionMode;
                })
              }
            >
              <option value="dry_run">dry_run</option>
              <option value="router_disconnect">router_disconnect</option>
            </select>
          </label>
          <label>
            轮询间隔
            <input
              type="number"
              min="10"
              value={config.service.poll_interval_seconds}
              onChange={(event) =>
                updateConfig((draft) => {
                  draft.service.poll_interval_seconds = Number(event.target.value);
                })
              }
            />
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={config.action.repeat_disconnect}
              onChange={(event) =>
                updateConfig((draft) => {
                  draft.action.repeat_disconnect = event.target.checked;
                })
              }
            />
            触发后允许重复断网
          </label>
        </div>
      </section>

      <footer className="command-bar">
        <button onClick={() => void saveConfig()} disabled={busy}>
          <Save size={17} />
          保存配置
        </button>
        <button onClick={() => void refreshTraffic()} disabled={busy}>
          <RefreshCw size={17} />
          刷新流量
        </button>
        <button onClick={() => void toggleMonitor()} disabled={busy}>
          {monitoring ? <CircleStop size={17} /> : <Power size={17} />}
          {monitoring ? "停止监控" : "启动监控"}
        </button>
        <button className="danger" onClick={() => void disconnectNow()} disabled={busy}>
          <PlugZap size={17} />
          测试断网
        </button>
        <div className="message">
          {status.triggered ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
          {message}
        </div>
      </footer>
    </main>
  );
}

export default App;
