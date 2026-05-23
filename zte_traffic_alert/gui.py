from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import platform
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from .config import (
    ActionConfig,
    AppConfig,
    RouterConfig,
    ServiceConfig,
    TrafficConfig,
    plan_bytes,
    threshold_bytes,
)
from .router import ZTERouterClient
from .service import TrafficAlertService, format_gib


class TrafficAlertGui:
    def __init__(self, root: tk.Tk, config_path: str):
        self.root = root
        self.config_path = Path(config_path)
        self.monitoring = False
        self.monitor_timer = ""
        self.worker_running = False

        self.root.title("中兴随身 WiFi 流量提醒")
        self.root.geometry("780x560")
        self.root.minsize(720, 520)

        self.router_url = tk.StringVar()
        self.admin_password = tk.StringVar()
        self.plan_gb = tk.StringVar()
        self.threshold_gb = tk.StringVar()
        self.poll_interval = tk.StringVar()
        self.mode = tk.StringVar()
        self.repeat_disconnect = tk.BooleanVar()

        self.used_text = tk.StringVar(value="-")
        self.remaining_text = tk.StringVar(value="-")
        self.trigger_text = tk.StringVar(value="-")
        self.action_text = tk.StringVar(value="-")
        self.last_check_text = tk.StringVar(value="尚未检查")
        self.status_text = tk.StringVar(value="就绪")

        self._build_ui()
        self._load_into_form()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(outer, text="中兴随身 WiFi 流量提醒", font=("", 20, "bold"))
        title.pack(anchor=tk.W)

        body = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, pady=(16, 12))

        settings = ttk.LabelFrame(body, text="配置", padding=14)
        status = ttk.LabelFrame(body, text="状态", padding=14)
        body.add(settings, weight=1)
        body.add(status, weight=1)

        self._entry(settings, "路由器地址", self.router_url, row=0)
        self._entry(settings, "后台密码", self.admin_password, row=1, show="*")
        self._entry(settings, "套餐总量 GB", self.plan_gb, row=2)
        self._entry(settings, "剩余多少 GB 断网", self.threshold_gb, row=3)
        self._entry(settings, "轮询间隔 秒", self.poll_interval, row=4)

        ttk.Label(settings, text="动作模式").grid(row=5, column=0, sticky=tk.W, pady=8)
        mode_box = ttk.Combobox(
            settings,
            textvariable=self.mode,
            values=("dry_run", "router_disconnect", "local_command"),
            state="readonly",
        )
        mode_box.grid(row=5, column=1, sticky=tk.EW, pady=8)

        repeat = ttk.Checkbutton(
            settings,
            text="触发后允许重复断网",
            variable=self.repeat_disconnect,
        )
        repeat.grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(4, 8))

        settings.columnconfigure(1, weight=1)

        self._status_row(status, "已用流量", self.used_text, row=0)
        self._status_row(status, "剩余流量", self.remaining_text, row=1)
        self._status_row(status, "是否触发", self.trigger_text, row=2)
        self._status_row(status, "执行动作", self.action_text, row=3)
        self._status_row(status, "检查时间", self.last_check_text, row=4)

        status.columnconfigure(1, weight=1)

        button_bar = ttk.Frame(outer)
        button_bar.pack(fill=tk.X)

        buttons = [
            ("保存配置", self.save_config),
            ("刷新流量", self.refresh_status),
            ("启动监控", self.start_monitor),
            ("停止监控", self.stop_monitor),
            ("测试断网", self.test_disconnect),
            ("安装开机自启", self.install_autostart),
        ]
        for text, command in buttons:
            ttk.Button(button_bar, text=text, command=command).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(outer, textvariable=self.status_text).pack(anchor=tk.W, pady=(12, 0))

    def _entry(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=8)
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row, column=1, sticky=tk.EW, pady=8)

    def _status_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        row: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=10)
        ttk.Label(parent, textvariable=variable, font=("", 13, "bold")).grid(
            row=row, column=1, sticky=tk.W, pady=10
        )

    def _load_into_form(self) -> None:
        config = self._load_json()
        router = config.get("router", {})
        traffic = config.get("traffic", {})
        service = config.get("service", {})
        action = config.get("action", {})

        self.router_url.set(str(router.get("base_url", "http://192.168.0.1")))
        self.admin_password.set(str(router.get("admin_password", "")))
        self.plan_gb.set(str(traffic.get("plan_gb", traffic.get("plan_gib", 241))))
        self.threshold_gb.set(
            str(
                traffic.get(
                    "disconnect_when_remaining_gb_lte",
                    traffic.get("alert_when_remaining_gib_lte", 2),
                )
            )
        )
        self.poll_interval.set(str(service.get("poll_interval_seconds", 300)))
        self.mode.set(str(action.get("mode", "dry_run")))
        self.repeat_disconnect.set(bool(action.get("repeat_disconnect", False)))

    def _load_json(self) -> dict:
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}

    def _config_from_form(self) -> AppConfig:
        plan = float(self.plan_gb.get())
        threshold = float(self.threshold_gb.get())
        interval = int(float(self.poll_interval.get()))
        return AppConfig(
            router=RouterConfig(
                base_url=self.router_url.get().strip() or "http://192.168.0.1",
                admin_password=self.admin_password.get(),
            ),
            traffic=TrafficConfig(
                plan_gb=plan,
                unit="GiB",
                disconnect_when_remaining_gb_lte=threshold,
            ),
            service=ServiceConfig(
                poll_interval_seconds=interval,
                state_path="zte_traffic_alert_state.json",
                log_path="zte_traffic_alert.log",
            ),
            action=ActionConfig(
                mode=self.mode.get(),
                repeat_disconnect=self.repeat_disconnect.get(),
            ),
        )

    def save_config(self) -> None:
        try:
            config = self._config_from_form()
            data = {
                "router": {
                    "base_url": config.router.base_url,
                    "admin_password": config.router.admin_password,
                    "request_timeout_seconds": config.router.request_timeout_seconds,
                    "disconnect_goform_ids": config.router.disconnect_goform_ids,
                },
                "traffic": {
                    "plan_gb": config.traffic.plan_gb,
                    "unit": config.traffic.unit,
                    "disconnect_when_remaining_gb_lte": (
                        config.traffic.disconnect_when_remaining_gb_lte
                    ),
                    "rx_field": config.traffic.rx_field,
                    "tx_field": config.traffic.tx_field,
                    "counter_mode": config.traffic.counter_mode,
                },
                "service": {
                    "poll_interval_seconds": config.service.poll_interval_seconds,
                    "state_path": config.service.state_path,
                    "log_path": config.service.log_path,
                },
                "action": {
                    "mode": config.action.mode,
                    "repeat_disconnect": config.action.repeat_disconnect,
                    "local_command": config.action.local_command,
                },
            }
            with self.config_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
            self.status_text.set(f"配置已保存：{self.config_path}")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def refresh_status(self) -> None:
        try:
            config = self._config_from_form()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        def work() -> tuple[int, int, bool]:
            snapshot = ZTERouterClient(config.router).get_traffic(config.traffic)
            remaining = max(plan_bytes(config.traffic) - snapshot.used_bytes, 0)
            triggered = remaining <= threshold_bytes(config.traffic)
            return snapshot.used_bytes, remaining, triggered

        def done(result: tuple[int, int, bool]) -> None:
            used, remaining, triggered = result
            self.used_text.set(format_gib(used))
            self.remaining_text.set(format_gib(remaining))
            self.trigger_text.set("是" if triggered else "否")
            self.action_text.set("未执行")
            self.last_check_text.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self.status_text.set("流量已刷新")

        self._run_background("正在读取路由器流量...", work, done)

    def start_monitor(self) -> None:
        if self.monitoring:
            return
        self.save_config()
        self.monitoring = True
        self.status_text.set("监控已启动")
        self._monitor_tick()

    def stop_monitor(self) -> None:
        self.monitoring = False
        if self.monitor_timer:
            self.root.after_cancel(self.monitor_timer)
            self.monitor_timer = ""
        self.status_text.set("监控已停止")

    def _monitor_tick(self) -> None:
        if not self.monitoring or self.worker_running:
            return

        try:
            config = self._config_from_form()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            self.stop_monitor()
            return

        def work():
            return TrafficAlertService(config).check_once()

        def done(result) -> None:
            if result.ok:
                self.used_text.set(format_gib(result.used_bytes))
                self.remaining_text.set(format_gib(result.remaining_bytes))
                self.trigger_text.set("是" if result.triggered else "否")
                self.action_text.set(result.action or "未执行")
                self.last_check_text.set(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                self.status_text.set("监控运行中")
            else:
                self.status_text.set(f"检查失败：{result.message}")
            if self.monitoring:
                delay_ms = max(config.service.poll_interval_seconds, 10) * 1000
                self.monitor_timer = self.root.after(delay_ms, self._monitor_tick)

        self._run_background("正在执行监控检查...", work, done)

    def test_disconnect(self) -> None:
        if not messagebox.askyesno("确认断网", "要立即调用路由器断网接口吗？"):
            return

        try:
            config = self._config_from_form()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        def work():
            return ZTERouterClient(config.router).disconnect()

        def done(result) -> None:
            self.action_text.set("router_disconnect")
            self.status_text.set(f"断网接口返回：{result}")

        self._run_background("正在调用断网接口...", work, done)

    def install_autostart(self) -> None:
        system = platform.system()
        project_dir = Path(__file__).resolve().parents[1]
        if system == "Darwin":
            command = [str(project_dir / "scripts" / "install_macos.sh")]
        elif system == "Windows":
            command = [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(project_dir / "scripts" / "install_windows.ps1"),
            ]
        else:
            messagebox.showinfo("暂不支持", f"当前系统暂不支持自动安装：{system}")
            return

        def work():
            completed = subprocess.run(
                command,
                cwd=project_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            return completed.stdout.strip() or "安装完成"

        def done(result: str) -> None:
            self.status_text.set(result)

        self._run_background("正在安装开机自启...", work, done)

    def _run_background(
        self,
        message: str,
        work: Callable,
        done: Callable,
    ) -> None:
        if self.worker_running:
            self.status_text.set("已有任务正在执行")
            return

        self.worker_running = True
        self.status_text.set(message)

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._task_error(error))
            else:
                self.root.after(0, lambda: self._task_done(done, result))

        threading.Thread(target=runner, daemon=True).start()

    def _task_done(self, done: Callable, result) -> None:
        self.worker_running = False
        try:
            done(result)
        except Exception as exc:
            self._task_error(exc)

    def _task_error(self, exc: Exception) -> None:
        self.worker_running = False
        self.status_text.set(f"执行失败：{exc}")
        messagebox.showerror("执行失败", str(exc))


def run_gui(config_path: str = "config.json") -> None:
    root = tk.Tk()
    TrafficAlertGui(root, config_path)
    root.mainloop()
