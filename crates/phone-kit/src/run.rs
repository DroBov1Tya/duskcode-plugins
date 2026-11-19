//! Running the tools behind a phone: a program with its arguments, never a shell, with a
//! time limit and a cap on what it prints, since its output is read as data.

use std::{process::Stdio, time::Duration};

use anyhow::{Context, Result, bail};
use tokio::{
    io::{AsyncRead, AsyncReadExt},
    process::Command,
};

/// What a tool may write to stderr; only its last line is kept.
const MAX_STDERR: u64 = 64 * 1024;

/// Runs `program` and returns its stdout, at most `max` bytes; a tool that prints more
/// or fails is an error that says why in the tool's own last line.
pub async fn run(program: &str, args: &[&str], limit: Duration, max: usize) -> Result<Vec<u8>> {
    let mut child = command(program)
        .args(args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("{program} did not start"))?;
    let stdout = child.stdout.take().context("no stdout")?;
    let stderr = child.stderr.take().context("no stderr")?;
    let work = async {
        let (out, err) = tokio::join!(
            read_capped(stdout, max),
            read_capped(stderr, MAX_STDERR as usize)
        );
        let status = child.wait().await?;
        anyhow::Ok((out?, err?, status))
    };
    let (out, err, status) = tokio::time::timeout(limit, work)
        .await
        .with_context(|| format!("{program} took too long"))??;
    if !status.success() {
        bail!("{}", last_line(&err));
    }
    if out.len() > max {
        bail!("{program} printed more than {max} bytes");
    }
    Ok(out)
}

/// Runs `program` with `input` on its stdin, for a tool that reads what it acts on there;
/// its output is dropped.
pub async fn run_with_input(
    program: &str,
    args: &[&str],
    input: &[u8],
    limit: Duration,
) -> Result<()> {
    use tokio::io::AsyncWriteExt;
    let mut child = command(program)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .with_context(|| format!("{program} did not start"))?;
    let mut stdin = child.stdin.take().context("no stdin")?;
    let stderr = child.stderr.take().context("no stderr")?;
    let work = async {
        stdin.write_all(input).await?;
        drop(stdin);
        let err = read_capped(stderr, MAX_STDERR as usize).await?;
        let status = child.wait().await?;
        anyhow::Ok((err, status))
    };
    let (err, status) = tokio::time::timeout(limit, work)
        .await
        .with_context(|| format!("{program} took too long"))??;
    if !status.success() {
        bail!("{}", last_line(&err));
    }
    Ok(())
}

/// A command with nothing on its stdin that dies with its handle.
pub fn command(program: &str) -> Command {
    let mut command = Command::new(program);
    command.stdin(Stdio::null()).kill_on_drop(true);
    command
}

/// Whether `error` says the program is not installed.
pub fn not_found(error: &anyhow::Error) -> bool {
    error
        .downcast_ref::<std::io::Error>()
        .is_some_and(|error| error.kind() == std::io::ErrorKind::NotFound)
}

/// Up to `max + 1` bytes, so a longer output shows; the rest is drained so the program
/// does not block on a full pipe.
async fn read_capped(mut from: impl AsyncRead + Unpin, max: usize) -> std::io::Result<Vec<u8>> {
    let mut kept = Vec::new();
    (&mut from)
        .take(max as u64 + 1)
        .read_to_end(&mut kept)
        .await?;
    tokio::io::copy(&mut from, &mut tokio::io::sink()).await?;
    Ok(kept)
}

/// The last line a tool wrote to stderr, which is where it says why.
pub fn last_line(stderr: &[u8]) -> String {
    let text = String::from_utf8_lossy(stderr);
    let line = text.lines().rev().find(|line| !line.trim().is_empty());
    line.unwrap_or("failed")
        .trim()
        .chars()
        .filter(|c| !c.is_control())
        .take(300)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn output_is_capped_and_failures_say_why() {
        let limit = Duration::from_secs(5);
        assert_eq!(run("echo", &["hi"], limit, 16).await.unwrap(), b"hi\n");
        assert!(run("echo", &["a long line"], limit, 4).await.is_err());
        let failed = run("ls", &["/no/such/folder"], limit, 16)
            .await
            .unwrap_err();
        assert!(format!("{failed}").contains("No such file"), "{failed}");
        let missing = run("no-such-program-here", &[], limit, 16)
            .await
            .unwrap_err();
        assert!(not_found(&missing));
    }
}
