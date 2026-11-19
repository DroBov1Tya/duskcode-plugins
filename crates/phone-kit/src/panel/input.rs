//! The user's touches, keys and scrolls on the panel's screen, sent to the device one
//! after another in the order they came: a drag's moves must not overtake its press.
//! A backend without touches by phase gets a tap or a swipe when the finger lifts; a
//! scroll is a drag that ends once the wheel rests.

use std::{sync::Arc, time::Duration};

use tokio::sync::mpsc;

use crate::{Key, Phase, Phone};

/// A wheel quiet this long ends its drag.
const SCROLL_REST: Duration = Duration::from_millis(150);
/// Below this many points a press that moved is still a tap.
const SLOP: u32 = 8;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Input {
    Touch(Phase, u32, u32),
    Key(Key),
    Text(String),
    Scroll { x: u32, y: u32, dx: i32, dy: i32 },
}

/// Starts the worker for `phone`; what fails is told through `failed`.
pub fn start<P: Phone>(
    phone: Arc<P>,
    failed: mpsc::Sender<String>,
) -> mpsc::UnboundedSender<(String, Input)> {
    let (sender, inputs) = mpsc::unbounded_channel();
    tokio::spawn(work(phone, inputs, failed));
    sender
}

async fn work<P: Phone>(
    phone: Arc<P>,
    mut inputs: mpsc::UnboundedReceiver<(String, Input)>,
    failed: mpsc::Sender<String>,
) {
    let touches = phone.touches();
    // The press of a backend without touches by phase, or of a scroll going on.
    let mut pressed: Option<(String, (u32, u32))> = None;
    let mut scroll: Option<(String, (u32, u32))> = None;
    // An input read while joining text, handled next.
    let mut held: Option<(String, Input)> = None;
    loop {
        let next = match (held.take(), &scroll) {
            (Some(next), _) => Some(next),
            (None, Some(_)) => match tokio::time::timeout(SCROLL_REST, inputs.recv()).await {
                Ok(next) => next,
                Err(_) => {
                    if let Some((id, at)) = scroll.take() {
                        report(&failed, phone.touch(&id, Phase::Up, at.0, at.1).await).await;
                    }
                    continue;
                }
            },
            (None, None) => inputs.recv().await,
        };
        let Some((id, input)) = next else { return };
        if !matches!(input, Input::Scroll { .. })
            && let Some((id, at)) = scroll.take()
        {
            report(&failed, phone.touch(&id, Phase::Up, at.0, at.1).await).await;
        }
        let result = match input {
            Input::Touch(phase, x, y) if touches => phone.touch(&id, phase, x, y).await,
            Input::Touch(Phase::Down, x, y) => {
                pressed = Some((id, (x, y)));
                Ok(())
            }
            Input::Touch(Phase::Move, ..) => Ok(()),
            Input::Touch(Phase::Up, x, y) => match pressed.take() {
                Some((id, from)) if moved(from, (x, y)) => phone.swipe(&id, from, (x, y)).await,
                Some((id, from)) => phone.tap(&id, from.0, from.1).await,
                None => Ok(()),
            },
            Input::Key(key) => phone.key(&id, key).await,
            Input::Text(mut text) => {
                // Text typed meanwhile joins in: one paste, not one per key.
                while let Ok(next) = inputs.try_recv() {
                    match next {
                        (next_id, Input::Text(more)) if next_id == id => text.push_str(&more),
                        other => {
                            held = Some(other);
                            break;
                        }
                    }
                }
                phone.type_text(&id, &text).await
            }
            Input::Scroll { x, y, dx, dy } if touches => {
                let (from, result) = match scroll.take() {
                    Some((_, at)) => (at, Ok(())),
                    None => ((x, y), phone.touch(&id, Phase::Down, x, y).await),
                };
                let to = (shift(from.0, dx), shift(from.1, dy));
                let result = match result {
                    Ok(()) => phone.touch(&id, Phase::Move, to.0, to.1).await,
                    error => error,
                };
                scroll = Some((id, to));
                result
            }
            Input::Scroll { .. } => Ok(()),
        };
        report(&failed, result).await;
    }
}

async fn report(failed: &mpsc::Sender<String>, result: anyhow::Result<()>) {
    if let Err(error) = result {
        let _ = failed.send(format!("{error:#}")).await;
    }
}

fn moved(from: (u32, u32), to: (u32, u32)) -> bool {
    from.0.abs_diff(to.0).max(from.1.abs_diff(to.1)) >= SLOP
}

/// `at` moved by `by`, never below zero; the backend refuses a point past the screen.
pub fn shift(at: u32, by: i32) -> u32 {
    at.saturating_add_signed(by)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_small_move_is_a_tap_and_a_scroll_stays_on_the_screen() {
        assert!(!moved((100, 100), (104, 96)));
        assert!(moved((100, 100), (100, 160)));
        assert_eq!(shift(5, -20), 0);
        assert_eq!(shift(5, 20), 25);
    }
}
