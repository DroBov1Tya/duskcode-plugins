//! The agent's tool: an MCP server on stdio with one tool that uses the running device
//! the way the user does in the panel. A picture of the screen is drawn in points, so a
//! place read off it is the place a touch goes to.

use std::sync::Arc;

use anyhow::{Context, Result, ensure};
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

use crate::{Button, Phone, picture};

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
}

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
        let result = match self.call(arguments).await {
            Ok(content) => CallToolResult::success(content),
            Err(error) => CallToolResult::error(vec![ContentBlock::text(format!("{error:#}"))]),
        };
        Ok(result.into())
    }
}

impl<P: Phone> Server<P> {
    async fn call(&self, arguments: Value) -> Result<Vec<ContentBlock>> {
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
                phone.tap(id, x, y).await?;
                format!("tapped {x},{y}")
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
                let bundle_id = arguments.bundle_id.context("give bundle_id")?;
                phone.launch(id, &bundle_id).await?;
                format!("launched {bundle_id}")
            }
        };
        Ok(vec![ContentBlock::text(said)])
    }
}

fn tool(spec: &Spec) -> Tool {
    let schema = json!({
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["screen", "ui", "tap", "swipe", "type", "button", "open_url", "launch"],
                "description": "screen: a picture in points; ui: the screen's elements with the points to tap"
            },
            "x": {"type": "integer", "minimum": 0, "description": "For tap and swipe: the place in points"},
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
    }
}
