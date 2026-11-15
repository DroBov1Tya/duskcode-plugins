//! A device's screen: one picture from simctl, and its size in points, read from the
//! profile of the device's type.

use anyhow::{Context, Result, ensure};
use phone_kit::run::run;

use crate::{
    listing::listing,
    run::{LIMIT, simctl},
};

/// The screen at full size, as JPEG; `udid` has been checked.
pub async fn take(udid: &str) -> Result<Vec<u8>> {
    simctl(&["io", udid, "screenshot", "--type=jpeg", "-"], LIMIT).await
}

/// The screen's width and height in points, upright.
pub async fn points(udid: &str) -> Result<(u32, u32)> {
    let listing = listing().await?;
    let profile = format!(
        "{}/Contents/Resources/profile.plist",
        listing.type_bundle(udid)?
    );
    let read = async |key: &str| -> Result<f64> {
        let raw = run(
            "plutil",
            &["-extract", key, "raw", "-o", "-", &profile],
            LIMIT,
            64,
        )
        .await?;
        let value: f64 = String::from_utf8_lossy(&raw)
            .trim()
            .parse()
            .with_context(|| format!("the device's profile has no {key}"))?;
        ensure!(
            value.is_finite() && value > 0.,
            "the device's profile has an odd {key}"
        );
        Ok(value)
    };
    let scale = read("mainScreenScale").await?;
    ensure!((1.0..=4.0).contains(&scale), "an odd screen scale: {scale}");
    let size = |pixels: f64| (pixels / scale).round() as u32;
    let (width, height) = (
        size(read("mainScreenWidth").await?),
        size(read("mainScreenHeight").await?),
    );
    ensure!(
        (1..=phone_kit::phone::MAX_POINT).contains(&width)
            && (1..=phone_kit::phone::MAX_POINT).contains(&height),
        "an odd screen size: {width}x{height}"
    );
    Ok((width, height))
}
