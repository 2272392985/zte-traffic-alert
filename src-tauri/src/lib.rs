use chrono::Local;
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;
use tauri::Manager;
use thiserror::Error;

#[derive(Debug, Error)]
enum AppError {
    #[error("配置错误：{0}")]
    Config(String),
    #[error("文件错误：{0}")]
    Io(#[from] std::io::Error),
    #[error("网络请求失败：{0}")]
    Http(#[from] reqwest::Error),
    #[error("路由器接口返回异常：{0}")]
    Router(String),
    #[error("JSON 错误：{0}")]
    Json(#[from] serde_json::Error),
}

impl Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct RouterConfig {
    base_url: String,
    admin_password: String,
    request_timeout_seconds: u64,
    disconnect_goform_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct TrafficConfig {
    plan_gb: f64,
    unit: String,
    disconnect_when_remaining_gb_lte: f64,
    rx_field: String,
    tx_field: String,
    counter_mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ServiceConfig {
    poll_interval_seconds: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ActionConfig {
    mode: String,
    repeat_disconnect: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AppConfig {
    router: RouterConfig,
    traffic: TrafficConfig,
    service: ServiceConfig,
    action: ActionConfig,
}

#[derive(Debug, Clone, Serialize)]
struct TrafficStatus {
    used_bytes: u64,
    remaining_bytes: u64,
    triggered: bool,
    action: String,
    rx_field: String,
    tx_field: String,
    checked_at: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            router: RouterConfig {
                base_url: "http://192.168.0.1".to_string(),
                admin_password: String::new(),
                request_timeout_seconds: 8,
                disconnect_goform_ids: vec![
                    "DISCONNECT_NETWORK".to_string(),
                    "DISCONNECT".to_string(),
                ],
            },
            traffic: TrafficConfig {
                plan_gb: 241.0,
                unit: "GiB".to_string(),
                disconnect_when_remaining_gb_lte: 2.0,
                rx_field: String::new(),
                tx_field: String::new(),
                counter_mode: "monthly".to_string(),
            },
            service: ServiceConfig {
                poll_interval_seconds: 300,
            },
            action: ActionConfig {
                mode: "dry_run".to_string(),
                repeat_disconnect: false,
            },
        }
    }
}

struct RouterClient {
    config: RouterConfig,
    client: Client,
}

impl RouterClient {
    fn new(config: RouterConfig) -> Result<Self, AppError> {
        let client = Client::builder()
            .cookie_store(true)
            .timeout(Duration::from_secs(config.request_timeout_seconds))
            .build()?;
        Ok(Self { config, client })
    }

    fn base_url(&self) -> String {
        self.config.base_url.trim_end_matches('/').to_string()
    }

    fn get_cmd(&self, commands: &[String]) -> Result<HashMap<String, Value>, AppError> {
        let cmd = commands.join(",");
        let url = format!(
            "{}/goform/goform_get_cmd_process?isTest=false&cmd={}&multi_data=1",
            self.base_url(),
            urlencoding::encode(&cmd)
        );
        let payload = self
            .client
            .get(url)
            .header("User-Agent", "zte-traffic-alert/tauri")
            .header("Referer", format!("{}/index.html", self.base_url()))
            .send()?
            .error_for_status()?
            .json::<HashMap<String, Value>>()?;
        Ok(payload)
    }

    fn post_goform(&self, fields: &[(&str, String)]) -> Result<HashMap<String, Value>, AppError> {
        let mut form = vec![("isTest", "false".to_string())];
        form.extend_from_slice(fields);
        let payload = self
            .client
            .post(format!("{}/goform/goform_set_cmd_process", self.base_url()))
            .header("User-Agent", "zte-traffic-alert/tauri")
            .header("Referer", format!("{}/index.html", self.base_url()))
            .form(&form)
            .send()?
            .error_for_status()?
            .json::<HashMap<String, Value>>()?;
        Ok(payload)
    }

    fn login_if_needed(&self) -> Result<(), AppError> {
        if self.config.admin_password.trim().is_empty() {
            return Ok(());
        }
        let payload = self.get_cmd(&["LD".to_string()])?;
        let ld = payload
            .get("LD")
            .and_then(value_to_string)
            .unwrap_or_default();
        let password = self.config.admin_password.clone();
        let mut hasher = Sha256::new();
        hasher.update(format!("{password}{ld}").as_bytes());
        let hashed = format!("{:x}", hasher.finalize());

        let response = self.post_goform(&[
            ("goformId", "LOGIN".to_string()),
            ("password", hashed),
        ])?;
        if is_success(&response) {
            return Ok(());
        }

        let fallback = self.post_goform(&[
            ("goformId", "LOGIN".to_string()),
            ("password", password),
        ])?;
        if is_success(&fallback) {
            Ok(())
        } else {
            Err(AppError::Router(format!("登录失败：{fallback:?}")))
        }
    }

    fn get_traffic(&self, traffic: &TrafficConfig) -> Result<TrafficStatus, AppError> {
        let mut fields = vec![
            "data_volume_used",
            "monthly_rx_bytes",
            "monthly_tx_bytes",
            "total_rx_bytes",
            "total_tx_bytes",
            "realtime_rx_bytes",
            "realtime_tx_bytes",
            "traffic_used",
            "flux_monthly_rx_bytes",
            "flux_monthly_tx_bytes",
        ]
        .into_iter()
        .map(String::from)
        .collect::<Vec<_>>();
        if !traffic.rx_field.is_empty() {
            fields.push(traffic.rx_field.clone());
        }
        if !traffic.tx_field.is_empty() {
            fields.push(traffic.tx_field.clone());
        }

        let payload = self.get_cmd(&fields)?;
        let rx_field = choose_field(
            &payload,
            &traffic.rx_field,
            &[
                "monthly_rx_bytes",
                "flux_monthly_rx_bytes",
                "month_rx_bytes",
                "rx_month_bytes",
                "total_rx_bytes",
            ],
        )?;
        let tx_field = choose_field(
            &payload,
            &traffic.tx_field,
            &[
                "monthly_tx_bytes",
                "flux_monthly_tx_bytes",
                "month_tx_bytes",
                "tx_month_bytes",
                "total_tx_bytes",
            ],
        )?;

        let rx = parse_byte_value(payload.get(&rx_field))?;
        let tx = parse_byte_value(payload.get(&tx_field))?;
        let used = rx.saturating_add(tx);
        let quota = plan_bytes(traffic)?;
        let remaining = quota.saturating_sub(used);
        let threshold = threshold_bytes(traffic)?;
        let mut action = String::new();
        let triggered = remaining <= threshold;

        if triggered && traffic.disconnect_when_remaining_gb_lte >= 0.0 {
            let app_config = load_config_from_disk()?;
            if app_config.action.mode == "router_disconnect" {
                self.disconnect()?;
                action = "router_disconnect".to_string();
            } else {
                action = "dry_run".to_string();
            }
        }

        Ok(TrafficStatus {
            used_bytes: used,
            remaining_bytes: remaining,
            triggered,
            action,
            rx_field,
            tx_field,
            checked_at: Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
        })
    }

    fn disconnect(&self) -> Result<String, AppError> {
        self.login_if_needed()?;
        let mut errors = Vec::new();
        for goform_id in &self.config.disconnect_goform_ids {
            let response = self.post_goform(&[("goformId", goform_id.clone())])?;
            if is_success(&response) || (!response.contains_key("result") && !response.is_empty()) {
                return Ok(format!("断网成功：{goform_id} {response:?}"));
            }
            errors.push(format!("{goform_id}: {response:?}"));
        }
        Err(AppError::Router(format!("断网接口失败：{}", errors.join("; "))))
    }
}

#[tauri::command]
fn load_config() -> Result<AppConfig, AppError> {
    load_config_from_disk()
}

#[tauri::command]
fn save_config(config: AppConfig) -> Result<AppConfig, AppError> {
    validate_config(&config)?;
    let path = config_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&path, serde_json::to_string_pretty(&config)?)?;
    Ok(config)
}

#[tauri::command]
fn check_traffic() -> Result<TrafficStatus, AppError> {
    let config = load_config_from_disk()?;
    let client = RouterClient::new(config.router)?;
    client.get_traffic(&config.traffic)
}

#[tauri::command]
fn disconnect_router() -> Result<String, AppError> {
    let config = load_config_from_disk()?;
    let client = RouterClient::new(config.router)?;
    client.disconnect()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .invoke_handler(tauri::generate_handler![
            load_config,
            save_config,
            check_traffic,
            disconnect_router
        ])
        .setup(|app| {
            let _ = app.path().app_config_dir();
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Tauri application");
}

fn load_config_from_disk() -> Result<AppConfig, AppError> {
    let path = config_path()?;
    if !path.exists() {
        let config = AppConfig::default();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(&path, serde_json::to_string_pretty(&config)?)?;
        return Ok(config);
    }
    let config = serde_json::from_str::<AppConfig>(&fs::read_to_string(path)?)?;
    validate_config(&config)?;
    Ok(config)
}

fn config_path() -> Result<PathBuf, AppError> {
    let base = dirs::config_dir()
        .or_else(|| dirs::home_dir().map(|home| home.join(".config")))
        .ok_or_else(|| AppError::Config("无法定位用户配置目录".to_string()))?;
    Ok(base.join("ZTE Traffic Alert").join("config.json"))
}

fn validate_config(config: &AppConfig) -> Result<(), AppError> {
    if config.traffic.plan_gb <= 0.0 {
        return Err(AppError::Config("套餐总量必须大于 0".to_string()));
    }
    if config.traffic.disconnect_when_remaining_gb_lte < 0.0 {
        return Err(AppError::Config("断网阈值不能小于 0".to_string()));
    }
    if config.service.poll_interval_seconds < 10 {
        return Err(AppError::Config("轮询间隔至少 10 秒".to_string()));
    }
    if !matches!(config.action.mode.as_str(), "dry_run" | "router_disconnect") {
        return Err(AppError::Config("动作模式不支持".to_string()));
    }
    Ok(())
}

fn plan_bytes(config: &TrafficConfig) -> Result<u64, AppError> {
    gib_like_bytes(config.plan_gb, &config.unit)
}

fn threshold_bytes(config: &TrafficConfig) -> Result<u64, AppError> {
    gib_like_bytes(config.disconnect_when_remaining_gb_lte, &config.unit)
}

fn gib_like_bytes(value: f64, unit: &str) -> Result<u64, AppError> {
    if value < 0.0 {
        return Err(AppError::Config("流量值不能小于 0".to_string()));
    }
    let multiplier = if unit.eq_ignore_ascii_case("GB") {
        1000_f64.powi(3)
    } else {
        1024_f64.powi(3)
    };
    Ok((value * multiplier) as u64)
}

fn choose_field(
    payload: &HashMap<String, Value>,
    configured: &str,
    candidates: &[&str],
) -> Result<String, AppError> {
    if !configured.is_empty() && payload.get(configured).is_some_and(has_value) {
        return Ok(configured.to_string());
    }
    candidates
        .iter()
        .find(|field| payload.get(**field).is_some_and(has_value))
        .map(|field| field.to_string())
        .ok_or_else(|| AppError::Router("找不到流量统计字段，请检查固件字段名".to_string()))
}

fn has_value(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::String(text) => !text.trim().is_empty(),
        _ => true,
    }
}

fn value_to_string(value: &Value) -> Option<String> {
    match value {
        Value::String(text) => Some(text.clone()),
        Value::Number(number) => Some(number.to_string()),
        Value::Bool(value) => Some(value.to_string()),
        _ => None,
    }
}

fn parse_byte_value(value: Option<&Value>) -> Result<u64, AppError> {
    match value {
        Some(Value::Number(number)) => number
            .as_u64()
            .ok_or_else(|| AppError::Router(format!("无法解析流量值：{number}"))),
        Some(Value::String(text)) => parse_byte_text(text),
        Some(other) => Err(AppError::Router(format!("无法解析流量值：{other}"))),
        None => Ok(0),
    }
}

fn parse_byte_text(text: &str) -> Result<u64, AppError> {
    let cleaned = text.trim().replace(',', "");
    if cleaned.is_empty() {
        return Ok(0);
    }
    if let Ok(value) = cleaned.parse::<u64>() {
        return Ok(value);
    }

    let mut parts = cleaned.split_whitespace();
    let number = parts
        .next()
        .ok_or_else(|| AppError::Router(format!("无法解析流量值：{text}")))?
        .parse::<f64>()
        .map_err(|_| AppError::Router(format!("无法解析流量值：{text}")))?;
    let unit = parts.next().unwrap_or("B").to_ascii_uppercase();
    let multiplier = match unit.as_str() {
        "B" => 1.0,
        "K" | "KB" | "KIB" => 1024.0,
        "M" | "MB" | "MIB" => 1024.0_f64.powi(2),
        "G" | "GB" | "GIB" => 1024.0_f64.powi(3),
        "T" | "TB" | "TIB" => 1024.0_f64.powi(4),
        _ => return Err(AppError::Router(format!("无法解析流量单位：{unit}"))),
    };
    Ok((number * multiplier) as u64)
}

fn is_success(payload: &HashMap<String, Value>) -> bool {
    payload
        .get("result")
        .and_then(value_to_string)
        .map(|value| {
            matches!(
                value.to_ascii_lowercase().as_str(),
                "0" | "success" | "ok" | "true"
            )
        })
        .unwrap_or(false)
}
