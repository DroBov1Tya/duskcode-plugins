# ios-simulator

Xcode's iOS Simulator beside your work. The panel (header icon, desktop app) picks a
device, starts and shuts it down, and shows its screen live: a click is a tap, a drag a
swipe, and Home and Lock press the device's buttons. The agent gets the `ios_simulator`
tool in every client: a picture of the screen in points, the screen's elements with the
points to tap, taps, swipes, typing, buttons, links and launching an installed app. It
acts on the first booted device.

1. Install Xcode from the App Store and open it once; add the iOS platform under
   Settings, Components if it is missing.
2. For touches, keys and a live screen, install AXe:
   `brew install cameroncooke/axe/axe`. Without it the panel shows pictures from simctl.
3. Install ios-simulator from Plugins, Workshop.

It may run `xcrun` (simctl) and `axe`, and read `~/Library/Developer`. It has no
network. macOS only.

The binary has two commands: `ios-simulator panel` speaks duskcode's ui wire,
`ios-simulator mcp` is the tool's MCP server on stdio.
