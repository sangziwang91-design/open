# AgentBridge Chat Loop extension

This unpacked Manifest V3 extension supports Chrome and Edge on Windows and is
scoped to `https://chatgpt.com/*`. It proxies gateway traffic through its service
worker, so the bearer token is never placed in the page DOM or sent to ChatGPT.

After the local gateway is running, load this directory as an unpacked extension,
open the extension options, save the loopback URL and token, then click **连接
AgentBridge** inside a ChatGPT conversation. That explicit arm action sends the
brain protocol once. Task transfer and result feedback are automatic until the
configured step limit, a human-decision result, a page reload, or manual disarm.

The page adapter is intentionally ChatGPT-specific. Other chat sites require a
separately tested DOM adapter; this package does not claim generic native-app or
generic website support.
