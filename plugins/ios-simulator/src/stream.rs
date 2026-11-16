//! A device's screen as it changes: AXe streams JPEG frames, each after its length as
//! four bytes, big-endian. The newest frame wins; one the panel has not taken yet is
//! dropped.

use std::process::Stdio;

use anyhow::{Context, Result, ensure};
use phone_kit::run::command;
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    sync::mpsc,
};

const FPS: &str = "30";
/// Half the device's pixels is still sharper than the panel draws it.
const SCALE: &str = "0.5";
const QUALITY: &str = "70";
/// A frame larger than this is not a JPEG of a phone's screen.
const MAX_FRAME: usize = 8 * 1024 * 1024;

/// Streams until `frames` closes or AXe stops; `udid` has been checked.
pub async fn watch(udid: &str, frames: mpsc::Sender<Vec<u8>>) -> Result<()> {
    let mut axe = command(crate::run::axe_program());
    axe.args([
        "stream-video",
        "--udid",
        udid,
        "--format",
        "raw",
        "--fps",
        FPS,
        "--scale",
        SCALE,
        "--quality",
        QUALITY,
    ])
    .stdout(Stdio::piped())
    .stderr(Stdio::null());
    let mut child = axe.spawn().context("AXe did not start")?;
    let mut out = child.stdout.take().context("AXe gave no output")?;
    loop {
        tokio::select! {
            frame = read_frame(&mut out) => {
                let _ = frames.try_send(frame?);
            }
            () = frames.closed() => return Ok(()),
        }
    }
}

/// One frame: its length, then its bytes.
pub async fn read_frame(out: &mut (impl AsyncRead + Unpin)) -> Result<Vec<u8>> {
    let mut length = [0u8; 4];
    out.read_exact(&mut length)
        .await
        .context("the stream ended")?;
    let length = u32::from_be_bytes(length) as usize;
    ensure!(
        (1..=MAX_FRAME).contains(&length),
        "a frame of {length} bytes"
    );
    let mut frame = vec![0; length];
    out.read_exact(&mut frame)
        .await
        .context("the stream ended")?;
    Ok(frame)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn frames_are_read_by_their_length() {
        let mut stream: &[u8] = &[
            0, 0, 0, 3, 0xFF, 0xD8, 1, 0, 0, 0, 2, 0xFF, 0xD8, 0, 0, 0, 9, 1,
        ];
        assert_eq!(read_frame(&mut stream).await.unwrap(), [0xFF, 0xD8, 1]);
        assert_eq!(read_frame(&mut stream).await.unwrap(), [0xFF, 0xD8]);
        assert!(read_frame(&mut stream).await.is_err(), "cut short");
        let mut empty: &[u8] = &[0, 0, 0, 0];
        assert!(read_frame(&mut empty).await.is_err());
        let mut huge: &[u8] = &[0xFF, 0xFF, 0xFF, 0xFF];
        assert!(read_frame(&mut huge).await.is_err());
    }
}
