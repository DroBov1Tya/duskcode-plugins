# duskcode plugins

The plugins of the duskcode store and its page, the Workshop:
<https://drobov1tya.github.io/duskcode-plugins/>. In the app they are under Plugins,
Workshop, one click to install.

## How a plugin gets to a user

1. A plugin lives in `plugins/<name>/`: its `plugin.yml` (see
   [Writing a plugin](https://github.com/DroBov1Tya/dusk_code/blob/main/docs/plugins.md))
   and, for a program, a Rust crate whose binary has the plugin's name.
2. A tag `<name>-v<version>` builds it for each system in its `platforms` and uploads
   `<name>-<version>-<os>-<arch>.tar.gz` to that tag's release.
3. A maintainer runs `scripts/publish.py` on their own machine. It reads every
   `plugin.yml` and the packages of their releases, writes `site/index.json` with each
   package's size and SHA-256, and signs it with the store's Ed25519 key from their
   keychain into `site/index.json.sig`. The key never reaches GitHub.
4. A push of `site/` puts the page and the signed list on GitHub Pages.

duskcode installs a plugin only when the list's signature checks against the key built
into it, the package has the size and hash the list names, it unpacks to plain files
inside its own folder, and its `plugin.yml` asks for exactly the permissions the list
showed the user.

## Plugins

| Plugin | What it does | Systems |
| --- | --- | --- |
| [telegram](plugins/telegram) | Talk to duskcode from Telegram: messages, answers, questions and approvals | macOS |

## Trying it locally

```sh
cargo build --release -p telegram
mkdir -p target/aarch64-apple-darwin/release && cp target/release/telegram target/aarch64-apple-darwin/release/
sh scripts/package.sh telegram aarch64-apple-darwin
scripts/publish.py --local     # signs with the key in your keychain
```

MIT.
