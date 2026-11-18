//! The panel's view, drawn from its state: the device menu at the top, what the user
//! must do, then the phone with its buttons, or the button that starts it.

use super::{
    State,
    wire::{ButtonIcon, ListItem, RowLayout, Size, Tone, Widget},
};

pub fn render(state: &State) -> Widget {
    let mut children = vec![head(state)];
    if let Some(blocker) = &state.setup.blocker {
        children.push(Widget::notice(
            blocker.clone(),
            Tone::Normal,
            Size::Body,
            state.setup.dependency_missing && state.setup.note.is_none(),
        ));
    }
    if let Some(note) = &state.setup.note {
        children.push(Widget::notice(
            note.clone(),
            Tone::Muted,
            Size::Small,
            state.setup.dependency_missing,
        ));
    }
    if let Some(error) = &state.error {
        children.push(Widget::text(error.clone(), Tone::Danger, Size::Small));
    }
    children.push(body(state));
    Widget::Column { children }
}

fn head(state: &State) -> Widget {
    let picker = match state.devices.is_empty() {
        true => Widget::text(state.title, Tone::Normal, Size::Title),
        false => Widget::List {
            id: "device",
            items: state.devices.iter().map(item).collect(),
            selected: state.chosen.clone(),
            menu: true,
        },
    };
    Widget::Row {
        layout: RowLayout::Toolbar,
        children: vec![
            picker,
            Widget::icon_button(
                "refresh",
                "Refresh",
                ButtonIcon::Refresh,
                state.busy.is_some(),
            ),
        ],
    }
}

fn item(device: &crate::Device) -> ListItem {
    let detail = match device.running {
        true => "on".to_owned(),
        false => device.detail.clone(),
    };
    ListItem {
        id: device.id.clone(),
        title: device.name.clone(),
        detail,
    }
}

fn body(state: &State) -> Widget {
    if let Some(busy) = state.busy {
        return Widget::Progress {
            text: busy.to_owned(),
        };
    }
    if !state.looked {
        return Widget::Progress {
            text: "Looking for devices".into(),
        };
    }
    let Some(device) = state.chosen_device() else {
        return match state.setup.blocker.is_some() {
            true => Widget::Column {
                children: Vec::new(),
            },
            false => Widget::text("No devices yet.", Tone::Muted, Size::Body),
        };
    };
    if !device.running {
        return Widget::Column {
            children: vec![
                Widget::text(format!("{} is off.", device.name), Tone::Muted, Size::Body),
                Widget::button("start", "Start", true),
            ],
        };
    }
    let screen = match state.size {
        Some((width, height)) => Widget::Screen {
            id: "screen",
            width,
            height,
            phone: true,
        },
        None => Widget::Progress {
            text: "Reading the screen".into(),
        },
    };
    let buttons = Widget::Row {
        layout: RowLayout::Center,
        children: vec![
            Widget::icon_button(
                "home",
                "Home",
                ButtonIcon::Home,
                state.setup.hardware_buttons_unavailable,
            ),
            Widget::icon_button(
                "lock",
                "Lock",
                ButtonIcon::Lock,
                state.setup.hardware_buttons_unavailable,
            ),
            Widget::icon_button("stop", "Shut down", ButtonIcon::Power, false),
        ],
    };
    Widget::Column {
        children: vec![screen, buttons],
    }
}
