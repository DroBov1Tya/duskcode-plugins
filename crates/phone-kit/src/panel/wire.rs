//! duskcode's ui wire, the part of it a phone panel uses: one JSON object per line on
//! stdin and stdout. The shapes are the core's (`dusk_protocol::plugin::{wire, view}`).

use serde::{Deserialize, Serialize};

/// The longest line the core reads from a plugin.
pub const MAX_LINE: usize = 4 * 1024 * 1024;
/// The largest frame the core takes, decoded.
pub const MAX_FRAME: usize = 3 * 1024 * 1024;
/// The longest line read from the core: its messages are short.
pub const MAX_IN: usize = 64 * 1024;

/// From the core.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ToPlugin {
    Open {
        part: String,
    },
    Close {
        part: String,
    },
    Event {
        part: String,
        widget: String,
        event: UiEvent,
    },
}

/// What a widget sent; places on a screen are in its own units, here points.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum UiEvent {
    Click,
    Input { value: String },
    Select { item: String },
    Tap { x: u32, y: u32 },
    Swipe { from: (u32, u32), to: (u32, u32) },
}

/// To the core.
#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum FromPlugin<'a> {
    View {
        part: &'a str,
        root: Widget,
    },
    Frame {
        part: &'a str,
        widget: &'a str,
        jpeg: String,
    },
    Notice {
        text: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Tone {
    Normal,
    Muted,
    Good,
    Danger,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Size {
    Title,
    Body,
    Small,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ListItem {
    pub id: String,
    pub title: String,
    pub detail: String,
}

/// The widgets a phone panel draws with.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Widget {
    Column {
        children: Vec<Widget>,
    },
    Row {
        children: Vec<Widget>,
    },
    Text {
        text: String,
        tone: Tone,
        size: Size,
    },
    Button {
        id: &'static str,
        label: &'static str,
        primary: bool,
        disabled: bool,
    },
    List {
        id: &'static str,
        items: Vec<ListItem>,
        selected: Option<String>,
        menu: bool,
    },
    Screen {
        id: &'static str,
        width: u32,
        height: u32,
        phone: bool,
    },
    Progress {
        text: String,
    },
}

impl Widget {
    /// A text, cut to what the core draws.
    pub fn text(text: impl Into<String>, tone: Tone, size: Size) -> Self {
        let text: String = text.into();
        Self::Text {
            text: text.chars().take(MAX_TEXT).collect(),
            tone,
            size,
        }
    }

    pub fn button(id: &'static str, label: &'static str, primary: bool) -> Self {
        Self::Button {
            id,
            label,
            primary,
            disabled: false,
        }
    }
}

/// The longest text a widget may carry.
const MAX_TEXT: usize = 4000;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn messages_read_and_write_as_the_core_has_them() {
        let event: ToPlugin = serde_json::from_str(
            r#"{"type":"event","part":"phone","widget":"screen","event":{"kind":"swipe","from":[10,700],"to":[10,200]}}"#,
        )
        .unwrap();
        assert_eq!(
            event,
            ToPlugin::Event {
                part: "phone".into(),
                widget: "screen".into(),
                event: UiEvent::Swipe {
                    from: (10, 700),
                    to: (10, 200)
                },
            }
        );
        assert!(serde_json::from_str::<ToPlugin>(r#"{"type":"open"}"#).is_err());
        let view = FromPlugin::View {
            part: "phone",
            root: Widget::Screen {
                id: "screen",
                width: 402,
                height: 874,
                phone: true,
            },
        };
        assert_eq!(
            serde_json::to_string(&view).unwrap(),
            r#"{"type":"view","part":"phone","root":{"kind":"screen","id":"screen","width":402,"height":874,"phone":true}}"#
        );
    }
}
