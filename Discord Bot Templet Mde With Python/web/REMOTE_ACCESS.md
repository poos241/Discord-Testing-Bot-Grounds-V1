# Making the Dashboard Accessible Outside Your Network

Your bot + dashboard currently only work on your home WiFi. Here are two ways
to let others (mods, friends) reach it from anywhere.

## Option A: Cloudflare Tunnel (recommended)

Free, no router changes, no port forwarding. Cloudflare gives you a public
URL like `https://your-dashboard.trycloudflare.com` that tunnels to your PC.

1. Download **cloudflared** for Windows:
   https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Open a terminal and run:
   ```
   cloudflared tunnel --url http://localhost:5000
   ```
3. It prints a public URL. Share that URL with whoever needs access.
4. Keep that terminal open while people need access (or set it up as a
   Windows service for always-on — see Cloudflare's docs).

**Note:** The free `trycloudflare.com` URL changes every time you restart.
For a permanent URL, create a free Cloudflare account and set up a named
tunnel (one-time setup, ~10 minutes).

**Discord OAuth:** If people log in through the tunnel URL, add that URL +
`/callback` to your Discord app's redirect URIs in the Developer Portal
(e.g. `https://your-dashboard.trycloudflare.com/callback`).

## Option B: Tailscale (trusted people only)

If it's just a few mods/friends, Tailscale creates a private network
between your devices — no public URL, no strangers can find it.

1. Install Tailscale on your PC: https://tailscale.com/download
2. Have each person install Tailscale and join your network (you approve them).
3. They visit `http://<your-tailscale-ip>:5000` (find it in the Tailscale app).
4. Same Discord OAuth note as above — add the Tailscale URL + `/callback`
   as a redirect URI.

## Security notes

- Anyone with the URL can reach the login page, but they still need a
  Discord account with Manage Server permission on your server to get in.
- Don't share the tunnel URL publicly — treat it like a private invite link.
- The dashboard sets `WEB_HOST=0.0.0.0` by default so it accepts connections
  from the tunnel. Don't change that.
