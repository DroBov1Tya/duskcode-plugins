# vphone

A [vphone](https://github.com/Lakr233/vphone-cli) virtual iPhone beside your work. The
panel (header icon, desktop app) picks a machine, starts it without its window and shuts
it down, and shows its screen: a click is a tap, a drag a swipe, and Home and Lock press
its keys. The agent gets the `vphone` tool in every client: a picture of the screen in
points, the screen's elements with the points to tap, taps, swipes, typing, home and
lock, links and launching an installed app. It acts on the first running machine.

1. Install vphone Launchpad from its releases, open it once and finish Host Setup
   (administrator password, Developer Tools access). Link its CLI:
   `ln -sf /Applications/vphone-launchpad.app/Contents/MacOS/vphone-launchpad-cli ~/.local/bin/`
2. Create a machine in Launchpad.
3. Install vphone from Plugins, Workshop.

It runs only `vphone-launchpad-cli status`, `vm list`, `vm start` and `vm stop`, never
anything that installs a bundle or firmware, creates a machine or changes the Mac's
security; those stay yours to do in Launchpad. It talks to a running machine through
its `vphone.sock` under `~/.vphone`. It has no network. macOS on Apple silicon only.

The binary has two commands: `vphone panel` speaks duskcode's ui wire, `vphone mcp` is
the tool's MCP server on stdio.
