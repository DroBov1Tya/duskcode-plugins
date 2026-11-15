//! A screen for the model: the picture scaled to the screen's size in points, so a
//! place read off it is the place a touch goes to.

use anyhow::{Context, Result, ensure};
use image::{ImageFormat, Limits, codecs::jpeg::JpegEncoder, imageops::FilterType};

const QUALITY: u8 = 80;
/// More than any phone's screen holds; a larger picture is not one.
const MAX_PIXELS: u32 = 8192;

/// Whether `bytes` start as a JPEG does.
pub fn is_jpeg(bytes: &[u8]) -> bool {
    bytes.starts_with(&[0xFF, 0xD8])
}

/// `jpeg` scaled to `width` by `height`, as JPEG.
pub fn in_points(jpeg: &[u8], (width, height): (u32, u32)) -> Result<Vec<u8>> {
    ensure!(is_jpeg(jpeg), "the screen is not a JPEG");
    ensure!(
        (1..=MAX_PIXELS).contains(&width) && (1..=MAX_PIXELS).contains(&height),
        "an odd screen size: {width}x{height}"
    );
    let mut reader = image::ImageReader::with_format(std::io::Cursor::new(jpeg), ImageFormat::Jpeg);
    let mut limits = Limits::default();
    limits.max_image_width = Some(MAX_PIXELS);
    limits.max_image_height = Some(MAX_PIXELS);
    reader.limits(limits);
    let picture = reader.decode().context("cannot read the screen")?;
    let picture = picture.resize_exact(width, height, FilterType::Triangle);
    let mut out = Vec::new();
    JpegEncoder::new_with_quality(&mut out, QUALITY)
        .encode_image(&picture.to_rgb8())
        .context("cannot encode the screen")?;
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_screen_is_scaled_to_points() {
        let mut jpeg = Vec::new();
        let picture = image::RgbImage::from_pixel(120, 260, image::Rgb([10, 200, 30]));
        JpegEncoder::new_with_quality(&mut jpeg, 80)
            .encode_image(&picture)
            .unwrap();
        let scaled = in_points(&jpeg, (40, 87)).unwrap();
        let back = image::load_from_memory(&scaled).unwrap();
        assert_eq!((back.width(), back.height()), (40, 87));
        assert!(in_points(b"not a picture", (40, 87)).is_err());
        assert!(in_points(&[0xFF, 0xD8, 0, 1], (40, 87)).is_err());
        assert!(in_points(&jpeg, (0, 87)).is_err());
    }
}
