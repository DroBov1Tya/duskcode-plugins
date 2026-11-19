//! Xcode's iOS Simulator as a [`Phone`]: simctl lists, boots and pictures the devices;
//! AXe, when installed, touches, types and streams the screen.

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use anyhow::{Context, Result, bail, ensure};
use phone_kit::{
    Appearance, Button, Device, Key, Phase, Phone, Setup,
    phone::{MAX_POINT, MAX_TYPED, is_bundle_id, is_openable},
    run::{run, run_with_input},
};
use tokio::sync::mpsc;

use crate::{
    hid::{Edge, Hid},
    input,
    listing::listing,
    run::{BOOT_LIMIT, LIMIT, axe, axe_program, device, simctl},
    screen, stream, tree,
};

const AXE_HINT: &str = "AXe adds a smooth live screen and the list of the screen’s elements. It installs with Homebrew.";
/// The pause before a launch the springboard refused is tried again.
const LAUNCH_RETRY: Duration = Duration::from_secs(1);
/// Between two pictures when there is no AXe to stream.
const POLL_PAUSE: Duration = Duration::from_millis(200);

#[derive(Default)]
pub struct Simulator {
    /// Xcode's input frameworks, loaded on the first touch.
    hid: OnceLock<Hid>,
    /// Where the touch going on now started from, for its moves and lift.
    edge: Mutex<Edge>,
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
            hardware_buttons_unavailable: false,
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
        let (size, hid) = (self.size(&udid).await?, self.hid().await?);
        let at = place((x, y), size)?;
        input::drag(hid, &udid, size, at, &[], Duration::ZERO).await
    }

    async fn swipe(&self, id: &str, from: (u32, u32), to: (u32, u32)) -> Result<()> {
        let udid = device(id)?;
        let (size, hid) = (self.size(&udid).await?, self.hid().await?);
        let (from, to) = (place(from, size)?, place(to, size)?);
        let places = input::line(from, to, input::SWIPE);
        input::drag(hid, &udid, size, from, &places, Duration::ZERO).await
    }

    fn touches(&self) -> bool {
        true
    }

    async fn touch(&self, id: &str, phase: Phase, x: u32, y: u32) -> Result<()> {
        let udid = device(id)?;
        let (size, hid) = (self.size(&udid).await?, self.hid().await?);
        let at = place((x, y), size)?;
        let edge = match phase {
            Phase::Down => {
                let edge = input::edge(at.1, size.1);
                *self.edge.lock().map_err(|_| anyhow::anyhow!("poisoned"))? = edge;
                edge
            }
            _ => *self.edge.lock().map_err(|_| anyhow::anyhow!("poisoned"))?,
        };
        hid.touch(&udid, phase, at, size, edge)
    }

    async fn type_text(&self, id: &str, text: &str) -> Result<()> {
        let udid = device(id)?;
        ensure!(!text.is_empty(), "nothing to type");
        ensure!(
            text.chars().count() <= MAX_TYPED,
            "at most {MAX_TYPED} characters at once"
        );
        let hid = self.hid().await?;
        // Key usages type what the device's layout maps them to; a paste types the text.
        run_with_input(
            "xcrun",
            &["simctl", "pbcopy", &udid],
            text.as_bytes(),
            LIMIT,
        )
        .await?;
        input::chord(hid, &udid, &[0xe3, input::V])
    }

    async fn key(&self, id: &str, key: Key) -> Result<()> {
        let udid = device(id)?;
        input::chord(self.hid().await?, &udid, input::usages(key))
    }

    async fn button(&self, id: &str, button: Button) -> Result<()> {
        let udid = device(id)?;
        let source = match button {
            Button::Home => 0,
            Button::Lock => 1,
            Button::SideButton => 0xbb8,
            Button::Siri => 0x0040_0002,
        };
        let hid = self.hid().await?;
        hid.button(&udid, source, true)?;
        tokio::time::sleep(input::STEP).await;
        hid.button(&udid, source, false)
    }

    async fn appearance(&self, id: &str, appearance: Appearance) -> Result<()> {
        let udid = device(id)?;
        let name = match appearance {
            Appearance::Light => "light",
            Appearance::Dark => "dark",
        };
        simctl(&["ui", &udid, "appearance", name], LIMIT).await?;
        Ok(())
    }

    async fn install(&self, id: &str, app: &Path) -> Result<String> {
        let udid = device(id)?;
        let app = app.to_str().context("an odd app path")?;
        ensure!(!app.starts_with('-'), "an odd app path");
        let plist = format!("{app}/Info.plist");
        let bundle_id = run(
            "plutil",
            &["-extract", "CFBundleIdentifier", "raw", "-o", "-", &plist],
            LIMIT,
            512,
        )
        .await
        .context("the app has no bundle ID")?;
        let bundle_id = String::from_utf8_lossy(&bundle_id).trim().to_owned();
        ensure!(is_bundle_id(&bundle_id), "the app's bundle ID is odd");
        simctl(&["install", &udid, app], BOOT_LIMIT).await?;
        Ok(bundle_id)
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
        let launch = ["launch", udid.as_str(), bundle_id];
        match simctl(&launch, LIMIT).await {
            // Right after Home the springboard refuses a launch for a moment.
            Err(error) if format!("{error:#}").contains("No such process") => {
                tokio::time::sleep(LAUNCH_RETRY).await;
                simctl(&launch, LIMIT).await?;
            }
            result => {
                result?;
            }
        }
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

impl Simulator {
    async fn hid(&self) -> Result<&Hid> {
        if let Some(hid) = self.hid.get() {
            return Ok(hid);
        }
        let simctl = run("xcrun", &["--find", "simctl"], LIMIT, 4096).await?;
        let simctl = PathBuf::from(String::from_utf8_lossy(&simctl).trim());
        // .../Contents/Developer/usr/bin/simctl
        let developer = simctl
            .ancestors()
            .nth(3)
            .context("cannot find Xcode's developer folder")?;
        let hid = Hid::load(developer)?;
        Ok(self.hid.get_or_init(|| hid))
    }
}

/// A point on a screen `size` points across, as the HID builder takes it.
pub fn place((x, y): (u32, u32), size: (u32, u32)) -> Result<(f64, f64)> {
    ensure!(
        x <= MAX_POINT.min(size.0) && y <= MAX_POINT.min(size.1),
        "a point off the screen: {x},{y} on {}x{}",
        size.0,
        size.1
    );
    Ok((f64::from(x), f64::from(y)))
}
