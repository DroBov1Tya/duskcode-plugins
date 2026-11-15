//! A phone the plugins drive: a simulator or a virtual machine. Places are in points,
//! the unit a screen's elements and touches are given in, so a place read off a picture
//! scaled to points is the place a touch goes to.

use std::{future::Future, time::Duration};

use anyhow::{Context, Result};
use serde::Deserialize;
use tokio::sync::mpsc;

/// A device that can be started.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Device {
    /// What the backend knows it by: a UDID or a machine's name.
    pub id: String,
    pub name: String,
    /// Its system, such as "iOS 26.2", or nothing when unknown.
    pub detail: String,
    pub running: bool,
}

/// What the user must do before devices can run, and what works only in part.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Setup {
    /// Nothing runs until this is done, such as installing Xcode.
    pub blocker: Option<String>,
    /// Works, but not all of it, such as touches without AXe.
    pub note: Option<String>,
}

/// The hardware buttons the agent and the panel press.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Button {
    Home,
    Lock,
    SideButton,
    Siri,
}

impl Button {
    pub fn name(self) -> &'static str {
        match self {
            Self::Home => "home",
            Self::Lock => "lock",
            Self::SideButton => "side_button",
            Self::Siri => "siri",
        }
    }
}

/// A backend. `id` is always one [`Phone::list`] gave; a backend still checks it,
/// since it reaches the arguments of a program.
pub trait Phone: Send + Sync + 'static {
    /// What the panel and the tool call it, such as "iOS Simulator".
    fn title(&self) -> &'static str;
    fn setup(&self) -> impl Future<Output = Setup> + Send;
    /// The devices, running ones first.
    fn list(&self) -> impl Future<Output = Result<Vec<Device>>> + Send;
    /// Starts a device and returns once its screen can be pictured.
    fn start(&self, id: &str) -> impl Future<Output = Result<()>> + Send;
    fn stop(&self, id: &str) -> impl Future<Output = Result<()>> + Send;
    /// The screen's width and height in points, upright.
    fn size(&self, id: &str) -> impl Future<Output = Result<(u32, u32)>> + Send;
    /// One picture of the screen as JPEG, at any resolution.
    fn frame(&self, id: &str) -> impl Future<Output = Result<Vec<u8>>> + Send;
    fn tap(&self, id: &str, x: u32, y: u32) -> impl Future<Output = Result<()>> + Send;
    fn swipe(
        &self,
        id: &str,
        from: (u32, u32),
        to: (u32, u32),
    ) -> impl Future<Output = Result<()>> + Send;
    /// Types into the focused field.
    fn type_text(&self, id: &str, text: &str) -> impl Future<Output = Result<()>> + Send;
    fn button(&self, id: &str, button: Button) -> impl Future<Output = Result<()>> + Send;
    /// The screen's elements, one short line each with the point to tap.
    fn tree(&self, id: &str) -> impl Future<Output = Result<String>> + Send;
    fn open_url(&self, id: &str, url: &str) -> impl Future<Output = Result<()>> + Send;
    fn launch(&self, id: &str, bundle_id: &str) -> impl Future<Output = Result<()>> + Send;

    /// Sends the screen's pictures as it changes until `frames` closes or the device
    /// fails. This one takes a picture every `pause`; a backend with a stream sends its
    /// own.
    fn watch(
        &self,
        id: &str,
        frames: mpsc::Sender<Vec<u8>>,
    ) -> impl Future<Output = Result<()>> + Send {
        async move {
            while !frames.is_closed() {
                let frame = self.frame(id).await?;
                // A frame the panel has not drawn yet is replaced, not queued.
                let _ = frames.try_send(frame);
                tokio::time::sleep(POLL_PAUSE).await;
            }
            Ok(())
        }
    }

    /// The device the agent's tool acts on: the first running one.
    fn current(&self) -> impl Future<Output = Result<Device>> + Send {
        async move {
            let devices = self.list().await?;
            devices
                .into_iter()
                .find(|device| device.running)
                .with_context(|| {
                    format!(
                        "no device is running: start one in the {} panel",
                        self.title()
                    )
                })
        }
    }
}

/// Between two pictures of a backend that has no stream.
const POLL_PAUSE: Duration = Duration::from_millis(100);

/// No device's screen is this many points across.
pub const MAX_POINT: u32 = 4096;
/// The most characters typed at once.
pub const MAX_TYPED: usize = 4096;

/// Whether `bundle_id` is a plain bundle ID, such as `com.apple.mobilesafari`, that
/// cannot be read as a flag.
pub fn is_bundle_id(bundle_id: &str) -> bool {
    !bundle_id.is_empty()
        && bundle_id.len() <= 255
        && !bundle_id.starts_with('-')
        && bundle_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '-' | '_'))
}

/// Whether `url` is a link a device may open: a web page or an app's own scheme, never
/// a file, and nothing that reads as a flag.
pub fn is_openable(url: &str) -> bool {
    let Some((scheme, rest)) = url.split_once(':') else {
        return false;
    };
    let plain_scheme = scheme
        .chars()
        .next()
        .is_some_and(|c| c.is_ascii_alphabetic())
        && scheme
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '-' | '.'));
    plain_scheme
        && !scheme.eq_ignore_ascii_case("file")
        && !rest.is_empty()
        && url.len() <= 4096
        && !url.chars().any(char::is_control)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_plain_bundle_ids_and_links_pass() {
        assert!(is_bundle_id("com.apple.mobilesafari"));
        for bad in ["", "--help", "com.app; rm", "a b"] {
            assert!(!is_bundle_id(bad), "{bad}");
        }
        assert!(is_openable("https://example.com/a?b=c"));
        assert!(is_openable("myapp://open"));
        for bad in [
            "file:///etc/passwd",
            "FILE:/x",
            "not a url",
            "-x:y",
            "https:",
            "a:\nb",
        ] {
            assert!(!is_openable(bad), "{bad}");
        }
    }
}
