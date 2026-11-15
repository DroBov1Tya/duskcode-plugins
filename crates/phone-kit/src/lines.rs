//! One line of input that nobody vouches for: read up to a limit, so a peer that never
//! sends a newline cannot grow it without end.

use anyhow::{Result, bail};
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt};

/// The next line without its newline, or `None` at the end. A line longer than `max`
/// bytes is an error: the reader is then mid-line and should be dropped.
pub async fn read_line<R: AsyncBufRead + Unpin>(
    reader: &mut R,
    max: usize,
) -> Result<Option<Vec<u8>>> {
    let mut line = Vec::new();
    let limit = u64::try_from(max).unwrap_or(u64::MAX).saturating_add(1);
    let read = reader.take(limit).read_until(b'\n', &mut line).await?;
    if read == 0 {
        return Ok(None);
    }
    if line.last() == Some(&b'\n') {
        line.pop();
    } else if line.len() > max {
        bail!("a line longer than {max} bytes");
    }
    if line.last() == Some(&b'\r') {
        line.pop();
    }
    Ok(Some(line))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn lines_are_read_until_the_limit() {
        let mut input: &[u8] = b"one\r\ntwo\nthree";
        assert_eq!(read_line(&mut input, 10).await.unwrap().unwrap(), b"one");
        assert_eq!(read_line(&mut input, 10).await.unwrap().unwrap(), b"two");
        assert_eq!(read_line(&mut input, 10).await.unwrap().unwrap(), b"three");
        assert!(read_line(&mut input, 10).await.unwrap().is_none());
        let mut long: &[u8] = b"0123456789abc\n";
        assert!(read_line(&mut long, 10).await.is_err());
        let mut exact: &[u8] = b"0123456789\n";
        assert_eq!(
            read_line(&mut exact, 10).await.unwrap().unwrap(),
            b"0123456789"
        );
    }
}
