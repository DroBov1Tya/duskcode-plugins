//! A running machine through its `vphone.sock`: one JSON object per connection, one
//! JSON line back. Touches go through vphoned's `input.*` methods, which take points,
//! never through the socket's own `tap`, which takes pixels.

use std::{path::PathBuf, time::Duration};

use anyhow::{Context, Result, bail, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use phone_kit::{
    Button,
    lines::read_line,
    phone::{MAX_POINT, MAX_TYPED, is_bundle_id, is_openable},
};
use serde::Deserialize;
use serde_json::{Value, json};
use tokio::{
    io::{AsyncWriteExt, BufReader},
    net::UnixStream,
};

const LIMIT: Duration = Duration::from_secs(30);
/// More than a screenshot at the size asked for; the guest's word is not taken for it.
const MAX_REPLY: usize = 8 * 1024 * 1024;
/// The longer side of the panel's pictures, in pixels: sharp enough, quick to send.
const FRAME_EDGE: u32 = 960;
const FRAME_QUALITY: f64 = 0.6;
/// Longer or non-ASCII text is pasted rather than typed key by key.
const MAX_KEYED: usize = 200;

pub struct Guest {
    socket: PathBuf,
}

#[derive(Deserialize)]
struct Reply {
    ok: bool,
    #[serde(default)]
    result: Value,
    #[serde(default)]
    error: Option<String>,
    #[serde(default)]
    guest_error: Option<GuestError>,
}

#[derive(Deserialize)]
struct GuestError {
    #[serde(default)]
    message: String,
    #[serde(default)]
    hint: Option<String>,
}

#[derive(Deserialize)]
struct Shot {
    data: String,
}

#[derive(Deserialize)]
struct Screen {
    width: f64,
    height: f64,
}

impl Guest {
    pub fn new(socket: PathBuf) -> Self {
        Self { socket }
    }

    /// The screen as JPEG, scaled down for the panel.
    pub async fn frame(&self) -> Result<Vec<u8>> {
        let params = json!({"max_dimension": FRAME_EDGE, "quality": FRAME_QUALITY});
        let shot: Shot = serde_json::from_value(self.rpc("screen.screenshot", params).await?)
            .context("the guest sent no screenshot")?;
        let jpeg = STANDARD
            .decode(shot.data.as_bytes())
            .context("the screenshot is not base64")?;
        ensure!(
            phone_kit::picture::is_jpeg(&jpeg),
            "the screenshot is not a JPEG"
        );
        Ok(jpeg)
    }

    /// The screen's size in points.
    pub async fn size(&self) -> Result<(u32, u32)> {
        let screen: Screen = serde_json::from_value(self.rpc("device.screen", json!({})).await?)
            .context("the guest sent no screen size")?;
        let point = |value: f64| -> Result<u32> {
            ensure!(
                value.is_finite() && (1.0..=MAX_POINT as f64).contains(&value),
                "an odd screen size"
            );
            Ok(value.round() as u32)
        };
        Ok((point(screen.width)?, point(screen.height)?))
    }

    pub async fn tap(&self, x: u32, y: u32) -> Result<()> {
        let (x, y) = (point(x)?, point(y)?);
        self.rpc("input.tap", json!({"x": x, "y": y}))
            .await
            .map(drop)
    }

    pub async fn swipe(&self, from: (u32, u32), to: (u32, u32)) -> Result<()> {
        let from = [point(from.0)?, point(from.1)?];
        let to = [point(to.0)?, point(to.1)?];
        self.rpc("input.swipe", json!({"from": from, "to": to}))
            .await
            .map(drop)
    }

    pub async fn type_text(&self, text: &str) -> Result<()> {
        ensure!(!text.is_empty(), "nothing to type");
        ensure!(
            text.chars().count() <= MAX_TYPED,
            "at most {MAX_TYPED} characters at once"
        );
        let method = match text.is_ascii() && text.len() <= MAX_KEYED {
            true => "input.type",
            false => "input.paste",
        };
        self.rpc(method, json!({"text": text})).await.map(drop)
    }

    /// A hardware key; the lock is the power key.
    pub async fn button(&self, button: Button) -> Result<()> {
        let name = match button {
            Button::Home => "home",
            Button::Lock | Button::SideButton => "power",
            Button::Siri => bail!("a vphone has no siri button"),
        };
        self.send(&json!({"t": "key", "name": name, "screen": false}))
            .await
            .map(drop)
    }

    pub async fn tree(&self) -> Result<String> {
        let tree = self
            .rpc("ui.tree", json!({"max_elements": crate::tree::MAX_LINES}))
            .await?;
        Ok(crate::tree::compact(&tree))
    }

    pub async fn open_url(&self, url: &str) -> Result<()> {
        ensure!(
            is_openable(url),
            "not a link a device opens: a web page or an app's own link"
        );
        self.rpc("apps.open_url", json!({"url": url}))
            .await
            .map(drop)
    }

    pub async fn launch(&self, bundle_id: &str) -> Result<()> {
        ensure!(is_bundle_id(bundle_id), "not a bundle ID");
        self.rpc("apps.launch", json!({"bundle_id": bundle_id}))
            .await
            .map(drop)
    }

    /// Calls a vphoned method and returns its `result`.
    async fn rpc(&self, method: &str, params: Value) -> Result<Value> {
        self.send(&json!({"t": "rpc", "method": method, "params": params}))
            .await
    }

    /// One request on a connection of its own; the reply's `result`, or why it failed.
    async fn send(&self, request: &Value) -> Result<Value> {
        let exchange = async {
            let mut stream = UnixStream::connect(&self.socket)
                .await
                .context("the machine's socket does not answer")?;
            let mut line = serde_json::to_vec(request)?;
            line.push(b'\n');
            stream.write_all(&line).await?;
            // The end of the request, as `nc -U` sends it.
            stream.shutdown().await?;
            let mut reader = BufReader::new(stream);
            read_line(&mut reader, MAX_REPLY)
                .await?
                .context("the machine closed without a reply")
        };
        let line = tokio::time::timeout(LIMIT, exchange)
            .await
            .context("the machine took too long")??;
        let reply: Reply =
            serde_json::from_slice(&line).context("the machine's reply is not JSON")?;
        if reply.ok {
            return Ok(reply.result);
        }
        let mut why = reply.error.unwrap_or_else(|| "the machine refused".into());
        if let Some(guest) = reply.guest_error {
            why = format!("{why}: {}", guest.message);
            if let Some(hint) = guest.hint {
                why = format!("{why} ({hint})");
            }
        }
        bail!(
            "{}",
            why.chars()
                .filter(|c| !c.is_control())
                .take(300)
                .collect::<String>()
        )
    }
}

fn point(value: u32) -> Result<u32> {
    ensure!(value <= MAX_POINT, "a point off the screen");
    Ok(value)
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use tokio::net::UnixListener;

    use super::*;

    const JPEG: &[u8] = &[0xFF, 0xD8, 0xFF, 0xE0, 1, 2, 3];

    /// A machine's socket that answers as vphoned does and keeps what it was asked.
    fn fake(name: &str) -> (PathBuf, Arc<Mutex<Vec<Value>>>) {
        let folder = std::env::temp_dir().join(format!("vp-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&folder);
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("vphone.sock");
        let listener = UnixListener::bind(&path).unwrap();
        let asked = Arc::new(Mutex::new(Vec::new()));
        let kept = Arc::clone(&asked);
        tokio::spawn(async move {
            while let Ok((stream, _)) = listener.accept().await {
                let kept = Arc::clone(&kept);
                tokio::spawn(async move {
                    let mut stream = BufReader::new(stream);
                    let line = read_line(&mut stream, 1 << 20).await.unwrap().unwrap();
                    let request: Value = serde_json::from_slice(&line).unwrap();
                    kept.lock().unwrap().push(request.clone());
                    let reply = answer(&request);
                    let mut stream = stream.into_inner();
                    stream.write_all(reply.as_bytes()).await.unwrap();
                });
            }
        });
        (path, asked)
    }

    fn answer(request: &Value) -> String {
        let reply = match (request["t"].as_str(), request["method"].as_str()) {
            (Some("ping"), _) => json!({"ok": true}),
            (Some("key"), _) => json!({"ok": true}),
            (Some("rpc"), Some("screen.screenshot")) => json!({"ok": true, "result": {
                "data": STANDARD.encode(JPEG), "mime_type": "image/jpeg", "width": 443, "height": 960,
                "point_width": 402, "point_height": 874, "coordinate_scale": 1.1, "bytes": 7,
                "region": {"x": 0, "y": 0, "width": 402, "height": 874}}}),
            (Some("rpc"), Some("device.screen")) => json!({"ok": true, "result": {
                "width": 402.0, "height": 874.0, "scale": 3, "orientation": 1, "locked": false, "screen_off": false}}),
            (Some("rpc"), Some("input.tap" | "input.swipe" | "input.type")) => {
                json!({"ok": true, "result": {}})
            }
            (Some("rpc"), Some("ui.tree")) => {
                json!({"ok": true, "result": {"count": 1, "elements": [
                {"label": "Settings", "role": "Button", "frame": {"x": 10, "y": 20, "width": 60, "height": 60}}]}})
            }
            (Some("rpc"), Some("bad.reply")) => return "not json\n".into(),
            (Some("rpc"), Some("no.newline")) => return "x".repeat(64),
            _ => json!({"ok": false, "error": "The machine refused the request.",
                        "guest_error": {"code": "not_found", "message": "Unknown method", "hint": "methods.list"}}),
        };
        format!("{reply}\n")
    }

    #[tokio::test]
    async fn the_guest_is_driven_in_points_through_its_socket() {
        let (path, asked) = fake("drive");
        let guest = Guest::new(path);
        guest.send(&json!({"t": "ping"})).await.unwrap();
        assert_eq!(guest.frame().await.unwrap(), JPEG);
        assert_eq!(guest.size().await.unwrap(), (402, 874));
        guest.tap(100, 200).await.unwrap();
        guest.swipe((10, 700), (10, 200)).await.unwrap();
        guest.type_text("hello").await.unwrap();
        guest.button(Button::Lock).await.unwrap();
        assert_eq!(guest.tree().await.unwrap(), "Button \"Settings\" at 40,50");
        let asked = asked.lock().unwrap().clone();
        assert_eq!(
            asked[1]["params"],
            json!({"max_dimension": 960, "quality": 0.6})
        );
        assert_eq!(
            asked[3],
            json!({"t": "rpc", "method": "input.tap", "params": {"x": 100, "y": 200}})
        );
        assert_eq!(
            asked[4]["params"],
            json!({"from": [10, 700], "to": [10, 200]})
        );
        assert_eq!(asked[5]["method"], "input.type");
        assert_eq!(
            asked[6],
            json!({"t": "key", "name": "power", "screen": false})
        );
    }

    #[tokio::test]
    async fn refusals_and_odd_replies_are_errors() {
        let (path, asked) = fake("odd");
        let guest = Guest::new(path);
        let refused = guest.rpc("nope", json!({})).await.unwrap_err();
        assert_eq!(
            format!("{refused}"),
            "The machine refused the request.: Unknown method (methods.list)"
        );
        assert!(guest.rpc("bad.reply", json!({})).await.is_err());
        assert!(guest.rpc("no.newline", json!({})).await.is_err());
        assert!(guest.tap(MAX_POINT + 1, 0).await.is_err());
        assert!(guest.launch("--help").await.is_err());
        assert!(guest.open_url("file:///etc/passwd").await.is_err());
        assert!(guest.button(Button::Siri).await.is_err());
        // Nothing refused here reached the guest.
        assert_eq!(asked.lock().unwrap().len(), 3);
        let gone = Guest::new(std::env::temp_dir().join("vp-none/vphone.sock"));
        assert!(gone.send(&json!({"t": "ping"})).await.is_err());
    }
}
