//! simctl through xcrun, and AXe, which touches, types and streams. A device is named
//! only by a UDID that parses as one, so nothing else reaches their arguments.

use std::time::Duration;

use anyhow::{Context, Result, ensure};
use phone_kit::run::run;

pub const LIMIT: Duration = Duration::from_secs(30);
/// A first boot builds the device's data and can take this long.
pub const BOOT_LIMIT: Duration = Duration::from_secs(180);
/// More than `simctl list -j` or a full-size screenshot prints.
const MAX_OUTPUT: usize = 32 * 1024 * 1024;

/// A UDID in the one form simctl prints.
pub fn device(udid: &str) -> Result<String> {
    let hex_at = |index: usize, c: char| match index {
        8 | 13 | 18 | 23 => c == '-',
        _ => c.is_ascii_hexdigit(),
    };
    ensure!(
        udid.len() == 36 && udid.chars().enumerate().all(|(index, c)| hex_at(index, c)),
        "not a simulator device"
    );
    Ok(udid.to_ascii_uppercase())
}

pub async fn simctl(args: &[&str], limit: Duration) -> Result<Vec<u8>> {
    let mut all = vec!["simctl"];
    all.extend_from_slice(args);
    run("xcrun", &all, limit, MAX_OUTPUT).await
}

pub async fn axe(args: &[&str]) -> Result<Vec<u8>> {
    run("axe", args, LIMIT, MAX_OUTPUT)
        .await
        .context("AXe could not reach the device")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_a_udid_reaches_simctl() {
        assert_eq!(
            device("543c1e74-f9cc-4eb5-81a0-e1470375459b").unwrap(),
            "543C1E74-F9CC-4EB5-81A0-E1470375459B"
        );
        for bad in [
            "booted",
            "--help",
            "all",
            "",
            "543C1E74 F9CC",
            "543C1E74-F9CC-4EB5-81A0-E1470375459BX",
        ] {
            assert!(device(bad).is_err(), "{bad}");
        }
    }
}
