# ios-simulator

Xcode's iOS Simulator beside your work. The panel (header icon, desktop app) picks a
device, starts and shuts it down, and shows its screen live: a click is a tap, a held
click a long press, a drag a drag, the wheel scrolls, keys and text typed while the
screen has focus go to the device, and Home and Lock press its buttons. The agent gets the `ios_simulator`
tool in every client: a picture of the screen in points, the screen's elements with the
points to tap, taps and long presses, swipes and drags along a path, typing, keys,
buttons, links, light or dark mode, and launching an app, installed or built (a `.app`
inside the chat's project or Xcode's DerivedData). It acts on the first booted device,
so what it does shows in the panel.

Touches, keys and buttons go straight to the simulator through Xcode's own frameworks
(CoreSimulator and SimulatorKit), as Simulator.app sends them; text goes through the
device's pasteboard and a paste, so it types the same on any keyboard layout and
replaces what the device's pasteboard held.

1. Install Xcode from the App Store and open it once; add the iOS platform under
   Settings, Components if it is missing.
2. Optionally install AXe, `brew install cameroncooke/axe/axe`, for a smoother live
   screen and the `ui` list of elements. Without it the panel shows pictures from simctl.
3. Install ios-simulator from Plugins, Workshop.

It may run `xcrun` (simctl) and `axe`, and read `~/Library/Developer`. It has no
network. macOS only.

The binary has two commands: `ios-simulator panel` speaks duskcode's ui wire,
`ios-simulator mcp` is the tool's MCP server on stdio.
