//! vphoned's `ui.tree`, made short for the model: one line for each element with a
//! label, with the point at its middle to tap. vphoned does not fix an element's keys,
//! so the usual names are tried; a tree read no other way is shown cut.

use serde_json::Value;

/// Past this many lines a screen is cut.
pub const MAX_LINES: usize = 300;
/// A label longer than this is cut.
const MAX_TEXT: usize = 120;
/// What is shown of a tree whose elements have no known shape.
const MAX_RAW: usize = 8 * 1024;

pub fn compact(tree: &Value) -> String {
    let elements = tree
        .get("elements")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default();
    let mut lines: Vec<String> = elements.iter().filter_map(line).take(MAX_LINES).collect();
    if lines.len() == MAX_LINES && elements.len() > MAX_LINES {
        lines.push("[cut: the screen has more]".into());
    }
    if !lines.is_empty() {
        return lines.join("\n");
    }
    if elements.is_empty() {
        return "nothing with a label is on the screen".into();
    }
    let raw = tree.to_string();
    let cut: String = raw.chars().take(MAX_RAW).collect();
    match cut.len() < raw.len() {
        true => format!("{cut} [cut]"),
        false => cut,
    }
}

fn line(element: &Value) -> Option<String> {
    let label = first_text(
        element,
        &["label", "text", "title", "value", "name", "identifier"],
    )?;
    let kind = first_text(element, &["role", "type", "class"]).unwrap_or_else(|| "Element".into());
    let (x, y) = middle(element)?;
    Some(format!("{kind} {label:?} at {x:.0},{y:.0}"))
}

fn first_text(element: &Value, keys: &[&str]) -> Option<String> {
    keys.iter().find_map(|key| {
        let text: String = element
            .get(key)?
            .as_str()?
            .trim()
            .chars()
            .filter(|c| !c.is_control())
            .take(MAX_TEXT)
            .collect();
        (!text.is_empty()).then_some(text)
    })
}

/// The middle of the element's frame, or its centre when it gives one.
fn middle(element: &Value) -> Option<(f64, f64)> {
    let number = |value: &Value, key: &str| {
        value
            .get(key)
            .and_then(Value::as_f64)
            .filter(|n| n.is_finite())
    };
    if let Some(center) = element.get("center") {
        return Some((number(center, "x")?, number(center, "y")?));
    }
    let frame = element.get("frame").unwrap_or(element);
    let (x, y) = (number(frame, "x")?, number(frame, "y")?);
    let (width, height) = (number(frame, "width")?, number(frame, "height")?);
    (width > 0. && height > 0.).then(|| (x + width / 2., y + height / 2.))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn labelled_elements_become_lines_to_tap() {
        let tree = json!({"count": 4, "elements": [
            {"label": "Settings", "role": "Button", "frame": {"x": 10, "y": 20, "width": 60, "height": 60}},
            {"text": "Wi\u{0007}-Fi", "center": {"x": 200, "y": 300}},
            {"label": "Hidden", "frame": {"x": 0, "y": 0, "width": 0, "height": 0}},
            {"role": "Group", "x": 1, "y": 1, "width": 5, "height": 5}
        ]});
        assert_eq!(
            compact(&tree),
            "Button \"Settings\" at 40,50\nElement \"Wi-Fi\" at 200,300"
        );
    }

    #[test]
    fn a_tree_of_another_shape_is_shown_cut() {
        assert_eq!(
            compact(&json!({"count": 0, "elements": []})),
            "nothing with a label is on the screen"
        );
        assert_eq!(
            compact(&json!("odd")),
            "nothing with a label is on the screen"
        );
        let other = json!({"elements": [{"what": "x".repeat(MAX_RAW)}]});
        let shown = compact(&other);
        assert!(shown.ends_with("[cut]") && shown.len() < MAX_RAW + 10);
    }
}
