//! A vphone machine as a [`Phone`]: Launchpad lists, starts and stops machines; a
//! running one is driven through its socket, found from the last listing.

use std::{collections::HashMap, path::PathBuf, sync::Mutex};

use anyhow::{Context, Result};
use phone_kit::{Button, Device, Phone, Setup};

use crate::{guest::Guest, launchpad};

#[derive(Default)]
pub struct Vphone {
    /// Each running machine's socket, from the last listing.
    sockets: Mutex<HashMap<String, PathBuf>>,
}

impl Vphone {
    /// The running machine `name`, looked up again when it was not in the last listing.
    async fn guest(&self, name: &str) -> Result<Guest> {
        if let Some(socket) = self.known(name) {
            return Ok(Guest::new(socket));
        }
        self.list().await?;
        let socket = self
            .known(name)
            .with_context(|| format!("{name} is not running"))?;
        Ok(Guest::new(socket))
    }

    fn known(&self, name: &str) -> Option<PathBuf> {
        self.sockets.lock().ok()?.get(name).cloned()
    }
}

impl Phone for Vphone {
    fn title(&self) -> &'static str {
        "vphone"
    }

    async fn setup(&self) -> Setup {
        launchpad::setup().await
    }

    async fn list(&self) -> Result<Vec<Device>> {
        let machines = launchpad::machines().await?;
        let sockets = machines
            .iter()
            .filter(|machine| machine.state == "running")
            .filter_map(|machine| Some((machine.name.clone(), launchpad::socket(machine)?)))
            .collect();
        if let Ok(mut known) = self.sockets.lock() {
            *known = sockets;
        }
        Ok(launchpad::devices(&machines))
    }

    async fn start(&self, id: &str) -> Result<()> {
        launchpad::start(id).await
    }

    async fn stop(&self, id: &str) -> Result<()> {
        launchpad::stop(id).await
    }

    async fn size(&self, id: &str) -> Result<(u32, u32)> {
        self.guest(id).await?.size().await
    }

    async fn frame(&self, id: &str) -> Result<Vec<u8>> {
        self.guest(id).await?.frame().await
    }

    async fn tap(&self, id: &str, x: u32, y: u32) -> Result<()> {
        self.guest(id).await?.tap(x, y).await
    }

    async fn swipe(&self, id: &str, from: (u32, u32), to: (u32, u32)) -> Result<()> {
        self.guest(id).await?.swipe(from, to).await
    }

    async fn type_text(&self, id: &str, text: &str) -> Result<()> {
        self.guest(id).await?.type_text(text).await
    }

    async fn button(&self, id: &str, button: Button) -> Result<()> {
        self.guest(id).await?.button(button).await
    }

    async fn tree(&self, id: &str) -> Result<String> {
        self.guest(id).await?.tree().await
    }

    async fn open_url(&self, id: &str, url: &str) -> Result<()> {
        self.guest(id).await?.open_url(url).await
    }

    async fn launch(&self, id: &str, bundle_id: &str) -> Result<()> {
        self.guest(id).await?.launch(bundle_id).await
    }
}
