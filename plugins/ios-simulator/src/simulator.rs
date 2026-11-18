//! Xcode's iOS Simulator as a [`Phone`]: simctl lists, boots and pictures the devices;
//! AXe, when installed, touches, types and streams the screen.

use std::{
    collections::HashMap,
    sync::{
        Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use anyhow::{Context, Result, bail, ensure};
use phone_kit::{
    Button, Device, Phone, Setup,
    phone::{MAX_POINT, MAX_TYPED, is_bundle_id, is_openable},
    run::run,
};
use tokio::sync::mpsc;

use crate::{
    listing::listing,
    run::{BOOT_LIMIT, LIMIT, axe, axe_program, device, simctl},
    screen, stream, tree,
};

const AXE_HINT: &str =
    "AXe lets you tap, swipe, and use the simulator’s hardware buttons. It installs with Homebrew.";
/// Between two pictures when there is no AXe to stream.
const POLL_PAUSE: Duration = Duration::from_millis(200);

#[derive(Default)]
pub struct Simulator {
    /// AXe answered when the setup was last looked at.
    axe: AtomicBool,
    /// Screen sizes in points by UDID; a device's type never changes.
    sizes: Mutex<HashMap<String, (u32, u32)>>,
}

impl Phone for Simulator {
    fn title(&self) -> &'static str {
        "iOS Simulator"
    }

    async fn setup(&self) -> Setup {
        let axe = run(axe_program(), &["--version"], LIMIT, 1024)
            .await
            .is_ok();
        self.axe.store(axe, Ordering::Relaxed);
        let note = (!axe).then(|| AXE_HINT.to_owned());
        let blocker = match run("xcrun", &["--find", "simctl"], LIMIT, 4096).await {
            Err(_) => Some("Install Xcode from the App Store, then open it once.".to_owned()),
            Ok(_) => match listing().await {
                Err(error) => Some(format!("simctl does not answer: {error:#}")),
                Ok(listing) if listing.runtimes().is_empty() => Some(
                    "Install the iOS platform in Xcode, under Settings, Components, then press Refresh."
                        .to_owned(),
                ),
                Ok(listing) if listing.devices().is_empty() => {
                    Some("Add an iPhone in Xcode, under Window, Devices and Simulators.".to_owned())
                }
                Ok(_) => None,
            },
        };
        Setup {
            blocker,
            note,
            dependency_missing: !axe,
            hardware_buttons_unavailable: !axe,
        }
    }

    async fn list(&self) -> Result<Vec<Device>> {
        Ok(listing().await?.devices())
    }

    async fn start(&self, id: &str) -> Result<()> {
        let udid = device(id)?;
        settle(simctl(&["boot", &udid], BOOT_LIMIT).await, "Booted")?;
        // `boot` returns before the device can draw; a picture taken then fails.
        simctl(&["bootstatus", &udid, "-b"], BOOT_LIMIT).await?;
        Ok(())
    }

    async fn stop(&self, id: &str) -> Result<()> {
        let udid = device(id)?;
        settle(simctl(&["shutdown", &udid], LIMIT).await, "Shutdown")
    }

    async fn size(&self, id: &str) -> Result<(u32, u32)> {
        let udid = device(id)?;
        if let Some(size) = self
            .sizes
            .lock()
            .ok()
            .and_then(|sizes| sizes.get(&udid).copied())
        {
            return Ok(size);
        }
        let size = screen::points(&udid).await?;
        if let Ok(mut sizes) = self.sizes.lock() {
            sizes.insert(udid, size);
        }
        Ok(size)
    }

    async fn frame(&self, id: &str) -> Result<Vec<u8>> {
        screen::take(&device(id)?).await
    }

    async fn tap(&self, id: &str, x: u32, y: u32) -> Result<()> {
        let udid = device(id)?;
        let (x, y) = (point(x)?, point(y)?);
        axe(&["tap", "-x", &x, "-y", &y, "--udid", &udid]).await?;
        Ok(())
    }

    async fn swipe(&self, id: &str, from: (u32, u32), to: (u32, u32)) -> Result<()> {
        let udid = device(id)?;
        let (start_x, start_y, end_x, end_y) =
            (point(from.0)?, point(from.1)?, point(to.0)?, point(to.1)?);
        let args = [
            "swipe",
            "--start-x",
            &start_x,
            "--start-y",
            &start_y,
            "--end-x",
            &end_x,
            "--end-y",
            &end_y,
            "--udid",
            &udid,
        ];
        axe(&args).await?;
        Ok(())
    }

    async fn type_text(&self, id: &str, text: &str) -> Result<()> {
        let udid = device(id)?;
        ensure!(!text.is_empty(), "nothing to type");
        ensure!(
            text.chars().count() <= MAX_TYPED,
            "at most {MAX_TYPED} characters at once"
        );
        // After `--`, text that starts with a dash is typed rather than read as a flag.
        axe(&["type", "--udid", &udid, "--", text]).await?;
        Ok(())
    }

    async fn button(&self, id: &str, button: Button) -> Result<()> {
        let udid = device(id)?;
        let name = match button {
            Button::Home => "home",
            Button::Lock => "lock",
            Button::SideButton => "side-button",
            Button::Siri => "siri",
        };
        axe(&["button", name, "--udid", &udid]).await?;
        Ok(())
    }

    async fn tree(&self, id: &str) -> Result<String> {
        tree::compact(&axe(&["describe-ui", "--udid", &device(id)?]).await?)
    }

    async fn open_url(&self, id: &str, url: &str) -> Result<()> {
        let udid = device(id)?;
        ensure!(
            is_openable(url),
            "not a link a device opens: a web page or an app's own link"
        );
        simctl(&["openurl", &udid, url], LIMIT).await?;
        Ok(())
    }

    async fn launch(&self, id: &str, bundle_id: &str) -> Result<()> {
        let udid = device(id)?;
        ensure!(is_bundle_id(bundle_id), "not a bundle ID");
        simctl(&["launch", &udid, bundle_id], LIMIT).await?;
        Ok(())
    }

    async fn watch(&self, id: &str, frames: mpsc::Sender<Vec<u8>>) -> Result<()> {
        let udid = device(id)?;
        if self.axe.load(Ordering::Relaxed) {
            return stream::watch(&udid, frames).await;
        }
        while !frames.is_closed() {
            let frame = screen::take(&udid)
                .await
                .context("cannot picture the screen")?;
            let _ = frames.try_send(frame);
            tokio::time::sleep(POLL_PAUSE).await;
        }
        Ok(())
    }
}

/// A device already in the state asked for is not a failure.
fn settle(result: Result<Vec<u8>>, state: &str) -> Result<()> {
    match result {
        Err(error) if format!("{error:#}").contains(&format!("current state: {state}")) => Ok(()),
        Err(error) => bail!(error),
        Ok(_) => Ok(()),
    }
}

fn point(value: u32) -> Result<String> {
    ensure!(value <= MAX_POINT, "a point off the screen");
    Ok(value.to_string())
}
