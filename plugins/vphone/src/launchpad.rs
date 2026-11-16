//! vphone Launchpad setup and machine management through its CLI. Host Setup is completed
//! by the owner in Launchpad.

use std::{path::PathBuf, time::Duration};

use anyhow::{Context, Result, ensure};
use phone_kit::{Device, Setup, run};
use serde::Deserialize;

const CLI: &str = "vphone-launchpad-cli";
const APP_NAME: &str = "vphone-launchpad.app";
const CLI_SUBPATH: &str = "Contents/MacOS/vphone-launchpad-cli";
const LIMIT: Duration = Duration::from_secs(60);
/// A first boot can take this long; the CLI waits for vphoned to answer.
const START_SECONDS: u64 = 300;
const MAX_OUTPUT: usize = 4 * 1024 * 1024;

const INSTALL: &str = "vphone Launchpad manages the virtual iPhone and its system bundle. Install Launchpad, then follow Host Setup in the app.";

pub fn user_app() -> Option<PathBuf> {
    let home = PathBuf::from(std::env::var_os("HOME")?);
    if !home.is_absolute() {
        return None;
    }
    Some(
        home.canonicalize()
            .ok()?
            .join("Applications")
            .join(APP_NAME),
    )
}

async fn install_setup() -> Setup {
    let silicon = run::run("/usr/sbin/sysctl", &["-n", "hw.optional.arm64"], LIMIT, 64).await;
    let version = run::run("/usr/bin/sw_vers", &["-productVersion"], LIMIT, 64).await;
    let supported = silicon.is_ok_and(|value| value == b"1\n")
        && version
            .ok()
            .and_then(|value| {
                std::str::from_utf8(&value)
                    .ok()?
                    .split('.')
                    .next()?
                    .parse::<u32>()
                    .ok()
            })
            .is_some_and(|major| major >= 15);
    let message = if supported {
        INSTALL
    } else {
        "vphone Launchpad requires macOS 15 or newer on an Apple silicon Mac."
    };
    Setup {
        blocker: Some(message.into()),
        dependency_missing: supported,
        ..Setup::default()
    }
}

/// What `status` says, the part that tells the next step.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Status {
    #[serde(default)]
    helper: String,
    #[serde(default)]
    can_install_bundles: bool,
    #[serde(default)]
    bundle_ready: bool,
    #[serde(default)]
    machines: u64,
}

/// One machine of `vm list`.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Machine {
    pub name: String,
    pub state: String,
    pub control_socket: Option<String>,
    #[serde(default)]
    pub ios: Option<String>,
}

pub async fn setup() -> Setup {
    match cli(&["status"], LIMIT).await {
        Err(error) if run::not_found(&error) => install_setup().await,
        Err(error) => Setup {
            blocker: Some(format!("vphone Launchpad does not answer: {error:#}")),
            ..Setup::default()
        },
        Ok(out) => match serde_json::from_slice::<Status>(&out) {
            Ok(status) => status.setup(),
            Err(_) => Setup {
                blocker: Some("vphone Launchpad gave a status this plugin cannot read.".into()),
                ..Setup::default()
            },
        },
    }
}

impl Status {
    fn setup(&self) -> Setup {
        let host = (!self.helper.starts_with("ready") || !self.can_install_bundles).then(|| {
            format!(
                "Finish Host Setup in vphone Launchpad (helper: {}); it needs your administrator password and Developer Tools access.",
                clean(&self.helper)
            )
        });
        let blocker = match (self.machines, &host) {
            (0, Some(host)) => Some(host.clone()),
            (0, None) if !self.bundle_ready => Some(
                "Install a VPhone.bundle in vphone Launchpad, then create a machine there.".into(),
            ),
            (0, None) => Some(
                "Create a machine in vphone Launchpad; it takes tens of GB and a while.".into(),
            ),
            _ => None,
        };
        let note = host.filter(|_| blocker.is_none());
        Setup {
            blocker,
            note,
            ..Setup::default()
        }
    }
}

pub async fn machines() -> Result<Vec<Machine>> {
    let out = cli(&["vm", "list"], LIMIT).await?;
    parse_machines(&out)
}

pub fn parse_machines(out: &[u8]) -> Result<Vec<Machine>> {
    let machines: Vec<Machine> = serde_json::from_slice(out).context("vm list gave no machines")?;
    Ok(machines
        .into_iter()
        .filter(|machine| is_name(&machine.name))
        .collect())
}

/// The machines as devices, running ones first.
pub fn devices(machines: &[Machine]) -> Vec<Device> {
    let mut devices: Vec<Device> = machines
        .iter()
        .map(|machine| {
            let running = machine.state == "running";
            let detail = match (&machine.ios, running) {
                (Some(ios), true) => format!("iOS {}", clean(ios)),
                (Some(ios), false) if machine.state == "stopped" => format!("iOS {}", clean(ios)),
                _ => clean(&machine.state),
            };
            Device {
                id: machine.name.clone(),
                name: machine.name.clone(),
                detail,
                running,
            }
        })
        .collect();
    devices.sort_by_key(|device| !device.running);
    devices
}

/// The machine's socket when it serves one: an absolute path to a `vphone.sock`.
pub fn socket(machine: &Machine) -> Option<PathBuf> {
    let path = PathBuf::from(machine.control_socket.as_ref()?);
    let plain = path.is_absolute()
        && path.file_name().is_some_and(|name| name == "vphone.sock")
        && !path
            .components()
            .any(|part| part == std::path::Component::ParentDir);
    plain.then_some(path)
}

/// Starts the machine without its window, the panel being its screen, and waits until
/// vphoned answers.
pub async fn start(name: &str) -> Result<()> {
    ensure!(is_name(name), "not a machine's name");
    let timeout = START_SECONDS.to_string();
    let args = [
        "vm",
        "start",
        name,
        "--headless",
        "--wait",
        "--timeout",
        &timeout,
    ];
    cli(&args, Duration::from_secs(START_SECONDS + 30)).await?;
    Ok(())
}

pub async fn stop(name: &str) -> Result<()> {
    ensure!(is_name(name), "not a machine's name");
    cli(&["vm", "stop", name], Duration::from_secs(120)).await?;
    Ok(())
}

/// A machine's name as Launchpad makes them, which never reads as a flag.
pub fn is_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && !name.starts_with(['-', '.'])
        && name
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
}

async fn cli(args: &[&str], limit: Duration) -> Result<Vec<u8>> {
    let result = run::run(CLI, args, limit, MAX_OUTPUT).await;
    if !result.as_ref().is_err_and(run::not_found) {
        return result;
    }
    let system_app = PathBuf::from("/Applications").join(APP_NAME);
    for app in user_app().into_iter().chain([system_app]) {
        let path = app.join(CLI_SUBPATH);
        if let Some(cli) = path.to_str().filter(|_| path.is_file()) {
            return run::run(cli, args, limit, MAX_OUTPUT).await;
        }
    }
    result
}

/// Text from the CLI, short and without control characters.
fn clean(text: &str) -> String {
    text.chars().filter(|c| !c.is_control()).take(120).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn machines_are_read_and_odd_names_left_out() {
        let out = br#"[
          {"name": "myphone", "state": "running", "controlSocket": "/Users/me/.vphone/machines/myphone/vphone.sock",
           "ios": "26.1 (23B85)", "cpuCount": 8, "bundle": "2.2.4"},
          {"name": "spare", "state": "stopped", "controlSocket": null},
          {"name": "new", "state": "busy: create", "controlSocket": null, "ios": "26.1 (23B85)"},
          {"name": "--help", "state": "stopped", "controlSocket": null}
        ]"#;
        let machines = parse_machines(out).unwrap();
        assert_eq!(machines.len(), 3);
        let devices = devices(&machines);
        assert_eq!(devices[0].id, "myphone");
        assert!(devices[0].running);
        assert_eq!(devices[0].detail, "iOS 26.1 (23B85)");
        assert_eq!(devices[2].detail, "busy: create");
        assert!(socket(&machines[0]).is_some());
        assert!(socket(&machines[1]).is_none());
        let odd = |path: &str| Machine {
            name: "a".into(),
            state: "running".into(),
            control_socket: Some(path.into()),
            ios: None,
        };
        assert!(socket(&odd("relative/vphone.sock")).is_none());
        assert!(socket(&odd("/a/../b/vphone.sock")).is_none());
        assert!(socket(&odd("/a/other.sock")).is_none());
        assert!(parse_machines(b"{}").is_err());
    }

    #[test]
    fn the_status_says_what_the_user_must_do() {
        let status = |json: &str| serde_json::from_str::<Status>(json).unwrap().setup();
        let ready = status(
            r#"{"helper":"ready (2.2.4)","canInstallBundles":true,"bundleReady":true,"machines":1}"#,
        );
        assert_eq!(ready, Setup::default());
        let host = status(r#"{"helper":"not installed","canInstallBundles":false,"machines":0}"#);
        assert!(host.blocker.unwrap().contains("Host Setup"));
        let none = status(
            r#"{"helper":"ready (2.2.4)","canInstallBundles":true,"bundleReady":true,"machines":0}"#,
        );
        assert!(none.blocker.unwrap().contains("Create a machine"));
        let partial = status(
            r#"{"helper":"outdated (1, app has 2)","canInstallBundles":false,"machines":2}"#,
        );
        assert!(partial.blocker.is_none() && partial.note.unwrap().contains("Host Setup"));
        assert!(!is_name("-x") && !is_name("a b") && is_name("my_phone-2.1"));
    }
}
