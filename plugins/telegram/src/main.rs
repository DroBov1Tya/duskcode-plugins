//! The bot's program, started by duskcode as the plugin's platform.

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    telegram::platform::run().await
}
