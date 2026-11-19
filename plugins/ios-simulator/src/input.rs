//! Gestures and keys made of HID events: a tap is a press and a lift, a swipe a press,
//! moves a frame apart and a lift, a key a press and a lift of its usage, with modifiers
//! held around it. Text goes through the device's pasteboard and a paste, since key
//! usages type what the device's keyboard layout says, not the text asked for.

use std::time::Duration;

use anyhow::Result;
use phone_kit::{Key, Phase};

use crate::hid::{Edge, Hid};

/// Between two moves of a drag: the builder drops moves closer than a frame apart.
pub const STEP: Duration = Duration::from_millis(20);
/// A swipe that gives no time takes this long.
pub const SWIPE: Duration = Duration::from_millis(300);
/// The longest press or drag.
pub const MAX_HOLD: Duration = Duration::from_secs(10);
/// A touch this close to the bottom edge starts the system's gesture there.
const EDGE: f64 = 4.;

const COMMAND: u32 = 0xe3;
const SHIFT: u32 = 0xe1;
/// The usage of `v`, pasted with command.
pub const V: u32 = 0x19;

/// The usages pressed together for `key`, modifiers first.
pub fn usages(key: Key) -> &'static [u32] {
    match key {
        Key::Return => &[0x28],
        Key::Escape => &[0x29],
        Key::Delete => &[0x2a],
        Key::Tab => &[0x2b],
        Key::Space => &[0x2c],
        Key::Home => &[0x4a],
        Key::PageUp => &[0x4b],
        Key::ForwardDelete => &[0x4c],
        Key::End => &[0x4d],
        Key::PageDown => &[0x4e],
        Key::Right => &[0x4f],
        Key::Left => &[0x50],
        Key::Down => &[0x51],
        Key::Up => &[0x52],
        Key::SelectAll => &[COMMAND, 0x04],
        Key::Undo => &[COMMAND, 0x1d],
        Key::Redo => &[COMMAND, SHIFT, 0x1d],
    }
}

/// Presses `usages` together and lets them go in reverse.
pub fn chord(hid: &Hid, udid: &str, usages: &[u32]) -> Result<()> {
    for usage in usages {
        hid.key(udid, *usage, true)?;
    }
    for usage in usages.iter().rev() {
        hid.key(udid, *usage, false)?;
    }
    Ok(())
}

/// The edge a touch starting at `y` on a screen `height` tall comes from.
pub fn edge(y: f64, height: u32) -> Edge {
    if y >= f64::from(height) - EDGE {
        Edge::Bottom
    } else {
        Edge::None
    }
}

/// The places of a straight drag from `from` to `to` taking `time`, one per step, the
/// last at `to`.
pub fn line(from: (f64, f64), to: (f64, f64), time: Duration) -> Vec<(f64, f64)> {
    let steps = (time.as_millis() / STEP.as_millis()).max(1) as usize;
    (1..=steps)
        .map(|step| {
            let part = step as f64 / steps as f64;
            (
                from.0 + (to.0 - from.0) * part,
                from.1 + (to.1 - from.1) * part,
            )
        })
        .collect()
}

/// A finger down at `from`, through `places` a step apart, and up at the last one.
pub async fn drag(
    hid: &Hid,
    udid: &str,
    size: (u32, u32),
    from: (f64, f64),
    places: &[(f64, f64)],
    hold: Duration,
) -> Result<()> {
    let edge = edge(from.1, size.1);
    hid.touch(udid, Phase::Down, from, size, edge)?;
    if !hold.is_zero() {
        tokio::time::sleep(hold.min(MAX_HOLD)).await;
    }
    let mut last = from;
    for place in places {
        tokio::time::sleep(STEP).await;
        hid.touch(udid, Phase::Move, *place, size, edge)?;
        last = *place;
    }
    hid.touch(udid, Phase::Up, last, size, edge)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_drag_ends_where_it_was_asked_to() {
        let places = line((10., 700.), (10., 100.), Duration::from_millis(300));
        assert_eq!(places.len(), 15);
        assert_eq!(places.last(), Some(&(10., 100.)));
        assert_eq!(line((0., 0.), (5., 5.), Duration::ZERO), vec![(5., 5.)]);
    }

    #[test]
    fn only_the_last_points_are_the_bottom_edge() {
        assert_eq!(edge(873., 874), Edge::Bottom);
        assert_eq!(edge(870., 874), Edge::Bottom);
        assert_eq!(edge(869., 874), Edge::None);
    }
}
