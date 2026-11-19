//! The agent's tool: an MCP server on stdio with one tool that uses the running device
//! the way the user does in the panel. A picture of the screen is drawn in points, so a
//! place read off it is the place a touch goes to.

use std::{
    path::{Path, PathBuf},
    sync::Arc,
    time::Duration,
};

use anyhow::{Context, Result, bail, ensure};
use base64::{Engine, engine::general_purpose::STANDARD};
use rmcp::{
    ErrorData, RoleServer, ServerHandler, ServiceExt,
    model::{
        CallToolRequestParams, CallToolResponse, CallToolResult, ContentBlock, Implementation,
        ListToolsResult, PaginatedRequestParams, ServerCapabilities, ServerConfig, Tool,
    },
    service::RequestContext,
};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::{Appearance, Button, Key, Phase, Phone, picture};

/// The tool as the model sees it.
pub struct Spec {
    pub name: &'static str,
    pub description: &'static str,
    /// The buttons `button` takes, by their names in [`Button`].
    pub buttons: &'static [&'static str],
}

/// Serves the tool on stdin and stdout until the client goes.
pub async fn serve<P: Phone>(phone: P, spec: Spec) -> Result<()> {
    let server = Server {
        phone: Arc::new(phone),
        spec,
    };
    let running = server
        .serve(rmcp::transport::stdio())
        .await
        .context("the MCP session did not start")?;
    running.waiting().await.context("the MCP session failed")?;
    Ok(())
}

struct Server<P> {
    phone: Arc<P>,
    spec: Spec,
}

#[derive(Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
enum Action {
    Screen,
    Ui,
    Tap,
    Swipe,
    Type,
    Button,
    OpenUrl,
    Launch,
    TouchPath,
    PressKey,
    SetAppearance,
}

/// One place of a `touch_path`, `dt_ms` after the one before it.
#[derive(Deserialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct PathPoint {
    x: u32,
    y: u32,
    #[serde(default)]
    dt_ms: u64,
}

/// The most places in one `touch_path`, and the longest it may take.
const MAX_PATH: usize = 200;
const MAX_PATH_MS: u64 = 30_000;
/// The longest press of a tap.
const MAX_HOLD_MS: u64 = 10_000;
/// The most presses of one key at once.
const MAX_COUNT: u32 = 20;
/// The `_meta` key the core puts the chat's project folder in.
const PROJECT_META: &str = "dev.duskcode/project";

#[derive(Deserialize, Debug)]
#[serde(deny_unknown_fields)]
struct Arguments {
    action: Action,
    x: Option<u32>,
    y: Option<u32>,
    to_x: Option<u32>,
    to_y: Option<u32>,
    text: Option<String>,
    button: Option<Button>,
    url: Option<String>,
    bundle_id: Option<String>,
    /// For tap: how long the finger stays down, a long press past 500.
    duration_ms: Option<u64>,
    points: Option<Vec<PathPoint>>,
    key: Option<Key>,
    count: Option<u32>,
    appearance: Option<Appearance>,
    app_path: Option<String>,
}

impl<P: Phone> ServerHandler for Server<P> {
    fn get_info(&self) -> ServerConfig {
        let mut info = ServerConfig::new(ServerCapabilities::builder().enable_tools().build());
        info.server_info = Implementation::new(self.spec.name, env!("CARGO_PKG_VERSION"));
        info
    }

    async fn list_tools(
        &self,
        _: Option<PaginatedRequestParams>,
        _: RequestContext<RoleServer>,
    ) -> Result<ListToolsResult, ErrorData> {
        Ok(ListToolsResult::with_all_items(vec![tool(&self.spec)]))
    }

    async fn call_tool(
        &self,
        request: CallToolRequestParams,
        _: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, ErrorData> {
        if request.name != self.spec.name {
            return Err(ErrorData::invalid_params(
                format!("no tool {}", request.name),
                None,
            ));
        }
        let arguments = Value::Object(request.arguments.unwrap_or_default());
        let project = request
            .meta
            .as_ref()
            .and_then(|meta| meta.get(PROJECT_META))
            .and_then(Value::as_str)
            .map(PathBuf::from);
        let result = match self.call(arguments, project.as_deref()).await {
            Ok(content) => CallToolResult::success(content),
            Err(error) => CallToolResult::error(vec![ContentBlock::text(format!("{error:#}"))]),
        };
        Ok(result.into())
    }
}

impl<P: Phone> Server<P> {
    async fn call(&self, arguments: Value, project: Option<&Path>) -> Result<Vec<ContentBlock>> {
        let arguments: Arguments =
            serde_json::from_value(arguments).context("invalid arguments")?;
        let phone = &self.phone;
        let device = phone.current().await?;
        let id = device.id.as_str();
        let at = || -> Result<(u32, u32)> {
            Ok((
                arguments.x.context("give x")?,
                arguments.y.context("give y")?,
            ))
        };
        let said = match arguments.action {
            Action::Screen => {
                let (jpeg, size) = tokio::try_join!(phone.frame(id), phone.size(id))?;
                let jpeg = picture::in_points(&jpeg, size)?;
                let detail = match device.detail.is_empty() {
                    true => String::new(),
                    false => format!(" ({})", device.detail),
                };
                let text = format!(
                    "{}{detail}, {}x{} points; the picture is in points.",
                    device.name, size.0, size.1
                );
                return Ok(vec![
                    ContentBlock::text(text),
                    ContentBlock::image(STANDARD.encode(jpeg), "image/jpeg"),
                ]);
            }
            Action::Ui => phone.tree(id).await?,
            Action::Tap => {
                let (x, y) = at()?;
                match arguments.duration_ms.unwrap_or(0) {
                    0 => phone.tap(id, x, y).await?,
                    held => {
                        ensure!(held <= MAX_HOLD_MS, "at most {MAX_HOLD_MS} ms");
                        phone.touch(id, Phase::Down, x, y).await?;
                        tokio::time::sleep(Duration::from_millis(held)).await;
                        phone.touch(id, Phase::Up, x, y).await?;
                    }
                }
                format!("tapped {x},{y}")
            }
            Action::TouchPath => {
                let points = arguments.points.context("give points")?;
                check_path(&points)?;
                let (first, last) = (points[0], points[points.len() - 1]);
                phone.touch(id, Phase::Down, first.x, first.y).await?;
                for point in &points[1..] {
                    tokio::time::sleep(Duration::from_millis(point.dt_ms)).await;
                    phone.touch(id, Phase::Move, point.x, point.y).await?;
                }
                phone.touch(id, Phase::Up, last.x, last.y).await?;
                format!("dragged through {} points", points.len())
            }
            Action::PressKey => {
                let key = arguments.key.context("give key")?;
                let count = arguments.count.unwrap_or(1);
                ensure!(
                    (1..=MAX_COUNT).contains(&count),
                    "count is 1 to {MAX_COUNT}"
                );
                for _ in 0..count {
                    phone.key(id, key).await?;
                }
                "pressed".into()
            }
            Action::SetAppearance => {
                let appearance = arguments.appearance.context("give appearance")?;
                phone.appearance(id, appearance).await?;
                "set".into()
            }
            Action::Swipe => {
                let from = at()?;
                let to = (
                    arguments.to_x.context("give to_x")?,
                    arguments.to_y.context("give to_y")?,
                );
                phone.swipe(id, from, to).await?;
                "swiped".into()
            }
            Action::Type => {
                let text = arguments.text.context("give text")?;
                phone.type_text(id, &text).await?;
                "typed".into()
            }
            Action::Button => {
                let button = arguments.button.context("give button")?;
                ensure!(
                    self.spec.buttons.contains(&button.name()),
                    "this device has no {} button",
                    button.name()
                );
                phone.button(id, button).await?;
                format!("pressed {}", button.name())
            }
            Action::OpenUrl => {
                let url = arguments.url.context("give url")?;
                phone.open_url(id, &url).await?;
                "opened".into()
            }
            Action::Launch => {
                let bundle_id = match (arguments.bundle_id, arguments.app_path) {
                    (Some(bundle_id), None) => bundle_id,
                    (None, Some(app)) => {
                        let app = built_app(Path::new(&app), project)?;
                        phone.install(id, &app).await?
                    }
                    _ => bail!("give bundle_id or app_path"),
                };
                phone.launch(id, &bundle_id).await?;
                let (width, height) = phone.size(id).await?;
                format!("launched {bundle_id}; the screen is {width}x{height} points")
            }
        };
        Ok(vec![ContentBlock::text(said)])
    }
}

/// The places of a drag: two at least, each a step after the last, not too long.
fn check_path(points: &[PathPoint]) -> Result<()> {
    ensure!(
        (2..=MAX_PATH).contains(&points.len()),
        "give 2 to {MAX_PATH} points"
    );
    let total: u64 = points.iter().map(|point| point.dt_ms.min(1000)).sum();
    ensure!(
        points.iter().all(|point| point.dt_ms <= 1000) && total <= MAX_PATH_MS,
        "dt_ms is at most 1000, the path at most {MAX_PATH_MS} ms"
    );
    Ok(())
}

/// `app` when it is a built `.app` inside the chat's project or Xcode's build output,
/// with links resolved, so nothing else is installed.
pub fn built_app(app: &Path, project: Option<&Path>) -> Result<PathBuf> {
    let app = app
        .canonicalize()
        .with_context(|| format!("no app at {}", app.display()))?;
    ensure!(
        app.extension().is_some_and(|extension| extension == "app") && app.is_dir(),
        "not a built .app folder"
    );
    let home = std::env::var_os("HOME").map(PathBuf::from);
    let derived = home.map(|home| home.join("Library/Developer/Xcode/DerivedData"));
    let allowed = [derived, project.map(Path::to_path_buf)]
        .into_iter()
        .flatten()
        .filter_map(|root| root.canonicalize().ok());
    for root in allowed {
        if app.starts_with(&root) {
            return Ok(app);
        }
    }
    bail!("the app must be inside the project or Xcode's DerivedData")
}

fn tool(spec: &Spec) -> Tool {
    let schema = json!({
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["screen", "ui", "tap", "swipe", "touch_path", "type", "press_key", "button", "open_url", "launch", "set_appearance"],
                "description": "screen: a picture in points; ui: the screen's elements with the points to tap"
            },
            "x": {"type": "integer", "minimum": 0, "description": "For tap and swipe: the place in points, origin top left. A swipe from the bottom 4 points is the home gesture"},
            "duration_ms": {"type": "integer", "minimum": 0, "maximum": MAX_HOLD_MS, "description": "For tap: hold this long; over 500 is a long press"},
            "points": {"type": "array", "maxItems": MAX_PATH, "items": {"type": "object", "properties": {"x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}, "dt_ms": {"type": "integer", "minimum": 0, "maximum": 1000}}, "required": ["x", "y"], "additionalProperties": false}, "description": "For touch_path: one finger down at the first, moved through the rest, lifted at the last"},
            "key": {"type": "string", "enum": ["return", "delete", "forward_delete", "tab", "escape", "space", "left", "right", "up", "down", "home", "end", "page_up", "page_down", "select_all", "undo", "redo"], "description": "For press_key"},
            "count": {"type": "integer", "minimum": 1, "maximum": MAX_COUNT, "description": "For press_key: times to press"},
            "appearance": {"type": "string", "enum": ["light", "dark"], "description": "For set_appearance"},
            "app_path": {"type": "string", "description": "For launch: a built .app in the project or DerivedData, installed first"},
            "y": {"type": "integer", "minimum": 0},
            "to_x": {"type": "integer", "minimum": 0, "description": "For swipe: where the finger lifts, in points"},
            "to_y": {"type": "integer", "minimum": 0},
            "text": {"type": "string", "description": "For type: the text, typed into the focused field"},
            "button": {"type": "string", "enum": spec.buttons, "description": "For button"},
            "url": {"type": "string", "description": "For open_url: a web page or an app's own link"},
            "bundle_id": {"type": "string", "description": "For launch: an installed app's bundle ID, such as com.apple.mobilesafari"}
        },
        "required": ["action"],
        "additionalProperties": false
    });
    Tool::new(
        spec.name,
        spec.description,
        schema.as_object().cloned().unwrap_or_default(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn arguments_are_strict() {
        let parse = |json: &str| serde_json::from_str::<Arguments>(json);
        let tap = parse(r#"{"action":"tap","x":10,"y":20}"#).unwrap();
        assert_eq!(
            (tap.action, tap.x, tap.y),
            (Action::Tap, Some(10), Some(20))
        );
        assert!(parse(r#"{"action":"tap","x":-1,"y":20}"#).is_err());
        assert!(parse(r#"{"action":"tap","z":1}"#).is_err());
        assert!(parse(r#"{"action":"reboot"}"#).is_err());
        assert!(parse(r#"{"action":"button","button":"power"}"#).is_err());
        assert!(parse(r#"{"action":"press_key","key":"reboot"}"#).is_err());
        let path =
            parse(r#"{"action":"touch_path","points":[{"x":1,"y":2},{"x":3,"y":4,"dt_ms":20}]}"#)
                .unwrap();
        assert!(check_path(&path.points.unwrap()).is_ok());
        let slow = [
            PathPoint {
                x: 0,
                y: 0,
                dt_ms: 0,
            },
            PathPoint {
                x: 1,
                y: 1,
                dt_ms: 5000,
            },
        ];
        assert!(check_path(&slow).is_err());
        assert!(check_path(&slow[..1]).is_err());
    }

    #[test]
    fn only_built_apps_in_the_project_install() {
        let project = std::env::temp_dir().join(format!("phone-kit-app-{}", std::process::id()));
        let app = project.join("build/My.app");
        std::fs::create_dir_all(&app).unwrap();
        std::fs::create_dir_all(project.join("notapp")).unwrap();
        assert!(built_app(&app, Some(&project)).is_ok());
        assert!(built_app(&app, None).is_err());
        assert!(built_app(&project.join("notapp"), Some(&project)).is_err());
        assert!(
            built_app(
                &project.join("build/../build/My.app"),
                Some(&project.join("build/My.app/.."))
            )
            .is_ok()
        );
        assert!(built_app(Path::new("/Applications/Safari.app"), Some(&project)).is_err());
        std::fs::remove_dir_all(&project).unwrap();
    }
}
