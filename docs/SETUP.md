# SETUP.md
# Personal AI Platform — Setup Manual
# Written for someone with zero Linux experience.
# Follow every step in order. Do not skip ahead.

---

## BEFORE YOU START

Take a breath. This looks long because it explains everything in plain English.
The actual work is not complicated — it just needs to be done in the right order.

**What you need:**

- Your Minisforum MS-S1 Max mini PC (unpacked, not yet turned on)
- A USB stick — at least 8GB, you don't mind wiping it
- A monitor with an HDMI or DisplayPort cable
- A USB keyboard
- A USB mouse
- An ethernet cable plugged into your router (WiFi works too but ethernet is more reliable for setup)
- Your regular Windows computer to do the preparation steps
- About 2 hours of time (most of it is waiting, not working)

---

## PART 1 — PREPARE THE USB STICK (on your Windows computer)

You are going to put Ubuntu on a USB stick. The mini PC will boot from this stick and install Ubuntu.

### Step 1 — Download Ubuntu

1. Open your browser and go to: https://ubuntu.com/download/desktop
2. Click the green **Download 24.04 LTS** button
3. Save the file — it is about 5GB, so this takes a while depending on your connection
4. The file will be named something like `ubuntu-24.04-desktop-amd64.iso`

### Step 2 — Download Rufus

Rufus is a free Windows tool that turns the Ubuntu file into a bootable USB stick.

1. Go to: https://rufus.ie
2. Click the download link for the latest version (the one without "portable" in the name)
3. Run the downloaded file — no installation needed, it opens directly

### Step 3 — Create the bootable USB stick

**Warning: This will erase everything on the USB stick. Make sure there is nothing important on it.**

1. Plug your USB stick into your Windows computer
2. Open Rufus (the file you just downloaded)
3. Under **Device**, select your USB stick from the dropdown. Make sure you pick the right one.
4. Under **Boot selection**, click **SELECT** and find the Ubuntu `.iso` file you downloaded
5. Leave everything else as default
6. Click **START**
7. A warning will appear saying the USB stick will be erased. Click **OK**
8. Wait — this takes about 10 minutes
9. When it says **READY** at the bottom, click **CLOSE**
10. Safely eject the USB stick from Windows

Your USB stick is now ready.

---

## PART 2 — BIOS SETTINGS (on the mini PC)

The BIOS is the mini PC's internal settings panel that runs before any operating system loads.
You need to change a few settings before installing Ubuntu.

**Important:** Do these steps before connecting power and turning the mini PC on for the first time.

### Step 4 — Connect everything

1. Connect the monitor to the mini PC using HDMI or DisplayPort
2. Connect the keyboard to a USB port
3. Connect the mouse to a USB port
4. Connect the ethernet cable
5. Do NOT connect power yet

### Step 5 — Enter the BIOS

1. Plug in the USB stick you created
2. Connect the power cable to the mini PC
3. Press the power button
4. Immediately and repeatedly press the **DELETE** key (some Minisforum models use **F2**)
   - You need to press it quickly, before the screen shows anything meaningful
   - If you miss it and something starts loading, hold the power button for 5 seconds to force it off, then try again
5. You should see a settings screen with lots of options — this is the BIOS

### Step 6 — Change the BIOS settings

Navigate using arrow keys and Enter. Mouse may or may not work here.

**Setting 1 — GPU memory allocation (most important)**

This controls how much of the 128GB memory is reserved for the graphics processor.
More memory here = larger AI models, faster AI performance.

- Look for a menu called **Advanced** or **AMD CBS** or **GFX Configuration**
- Find a setting called **UMA Frame Buffer Size** or **iGPU Memory** or **Shared Memory**
- Change it to the highest available option — typically **64G** or **Auto** (choose the largest fixed value, not Auto)
- This gives the GPU maximum memory for running AI models

**Setting 2 — Auto power-on after power loss**

This makes the mini PC automatically turn back on if power is cut and restored.
Important for a machine you want always available.

- Look for **Power** menu or **Advanced** → **Power Management**
- Find **Restore on AC Power Loss** or **AC Power Recovery**
- Set it to **Power On**

**Setting 3 — Disable sleep and hibernate**

The mini PC should never sleep on its own — it needs to stay on and available.

- In the same Power Management area
- Find **S3 Sleep** or **Suspend State** or **Sleep State**
- Set it to **Disabled** or **S0** (S0 means always on)

**Setting 4 — Boot order**

Tell the BIOS to try booting from the USB stick first.

- Find **Boot** menu
- Find **Boot Priority** or **Boot Order**
- Move **USB** or **Removable Devices** to the top of the list
  (Usually done by selecting it and pressing + or F5/F6, or there may be a drag interface)

### Step 7 — Save and exit BIOS

- Press **F10** to save and exit (this is almost universal)
- Confirm with **Yes** or **OK** when prompted
- The mini PC will restart

---

## PART 3 — INSTALL UBUNTU

The mini PC will restart and boot from your USB stick. You will see Ubuntu loading.
This may take a minute — you might see a purple or black screen with dots for a while. That is normal.

### Step 8 — Start the installer

1. You will eventually see a screen with **Try Ubuntu** and **Install Ubuntu** options
2. Click **Install Ubuntu**

### Step 9 — Language and keyboard

1. Select your language (English or your preferred language)
2. Click **Continue**
3. Select your keyboard layout
4. Click **Continue**

### Step 10 — Installation type

1. You will be asked what kind of installation you want
2. Select **Normal installation**
3. Check the box **Download updates while installing Ubuntu**
4. Check the box **Install third-party software** (this helps with hardware drivers)
5. Click **Continue**

### Step 11 — Disk setup

**Warning: This will erase Windows and everything on the mini PC's internal drive.**
This is what you want — the mini PC is becoming a dedicated Linux server.

1. Select **Erase disk and install Ubuntu**
2. Click **Install Now**
3. A confirmation dialog will appear listing what will be erased
4. Click **Continue**

### Step 12 — Location

1. Click on your location on the map, or type your city
2. Click **Continue**

### Step 13 — Create your account

1. **Your name:** Type your name (e.g. your first name)
2. **Your computer's name:** Type `ms-s1` — this will be the machine's name on the network
3. **Username:** Type `jarvis` — this is the system username used by all platform services
4. **Password:** Choose a password you will remember — you will need it occasionally
5. **Confirm password:** Type it again
6. Select **Require my password to log in**
7. Click **Continue**

### Step 14 — Wait for installation

Ubuntu is now installing. This takes about 20-30 minutes. You will see a progress bar and slides.
You do not need to do anything.

### Step 15 — Restart

1. When installation is complete, a dialog says **Installation Complete**
2. Click **Restart Now**
3. You will see a message saying **Please remove the installation medium**
4. Remove the USB stick
5. Press **Enter**
6. The mini PC restarts and boots into Ubuntu

---

## PART 4 — FIRST BOOT

### Step 16 — Log in

1. You will see a login screen with your name
2. Click on your name
3. Type your password
4. Press Enter

### Step 17 — Initial setup screens

Ubuntu shows a few welcome screens on first boot:

1. **Online Accounts** — click **Skip**
2. **Ubuntu Pro** — select **Skip for now**, click **Next**
3. **Help improve Ubuntu** — your choice, then click **Next**
4. **Privacy** — click **Next**
5. Click **Done**

You are now on the Ubuntu desktop. It looks similar to a regular computer desktop.

### Step 18 — Connect to WiFi (if not using ethernet)

If you are using ethernet, skip this step — you are already connected.

1. Click the icons in the top right corner of the screen
2. Click **Wi-Fi Not Connected** or the WiFi icon
3. Select your network and enter your password

---

## PART 5 — OPEN THE TERMINAL

The terminal is a text-based way to give instructions to the computer.
It looks intimidating but you are just typing commands that someone has already figured out.
Think of it like a very precise text message to the computer.

### Step 19 — Open the terminal

1. Press the keys **Ctrl + Alt + T** at the same time
2. A dark window opens with some text ending in `$`
3. That `$` means the terminal is ready for your next command

**Important note about passwords in the terminal:**
When you type a password in the terminal, nothing appears on screen — no dots, no stars, nothing.
This is a security feature, not a bug. Just type your password normally and press Enter.

**Important note about commands:**
Type commands exactly as written, including capital letters, spaces, and punctuation.
After typing a command, press Enter to run it.
Some commands ask you `[Y/n]` or `[y/N]` — type `y` and press Enter to confirm.

---

## PART 6 — RUN THE PLATFORM SETUP SCRIPT

One command installs everything. The script handles all the complexity so you don't have to.

### Step 20 — Download and run the setup script

Type this command in the terminal exactly as written and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR-GITHUB-USERNAME/YOUR-REPO/main/scripts/setup.sh | bash
```

**Note:** Replace `YOUR-GITHUB-USERNAME` and `YOUR-REPO` with your actual GitHub details once the project repository is created. This will be updated in the documentation before you need it.

The script will now run. Here is what it does and roughly how long each part takes:

1. **Updates the system** (5-10 minutes) — downloads the latest security fixes
2. **Installs Tailscale** (1-2 minutes) — sets up remote access
3. **Installs Caddy** (1 minute) — sets up the web server
4. **Installs Python** (1 minute) — the programming language the platform runs on
5. **Installs Node.js** (1-2 minutes) — needed for the web interfaces
6. **Installs Git** (under 1 minute) — version control
7. **Installs Ollama** (1 minute) — the AI model server
8. **Creates the directory structure** (instant) — organises where everything lives
9. **Downloads AI models** (30-90 minutes depending on internet speed) — this is the long part
10. **Sets up all services** (2-3 minutes) — makes everything start automatically
11. **Runs validation** (1-2 minutes) — checks everything worked

You will see text scrolling past. This is normal — it is showing you what is happening.
If you see the word **error** in red, take a photo of the screen and refer to the troubleshooting section at the end of this document.

### Step 21 — Authenticate Tailscale

During the setup script, it will pause and show you something like this:

```
To authenticate, visit:
https://login.tailscale.com/a/xxxxxxxxxx
```

1. Open that URL on any device — your phone or your regular computer
2. Log in to Tailscale (create a free account if you don't have one)
3. Click **Authenticate**
4. Go back to the terminal — it will continue automatically

### Step 22 — Wait for models to download

The three AI models are large files:
- qwen2.5:14b — about 9GB
- qwen2.5-coder:32b — about 20GB
- qwen2.5:72b-instruct-q4_K_M — about 44GB

Total: roughly 73GB. On a fast connection this takes 30-60 minutes.
On a slower connection it may take several hours.

The terminal shows download progress. You can leave it running and come back.

### Step 23 — Setup complete

When the script finishes, it runs a validation check. You will see something like:

```
============================================
PLATFORM VALIDATION
============================================
✓ Tailscale        running
✓ Caddy            running
✓ Ollama           running
✓ Models           3/3 available
✓ Chat backend     running
✓ Chat frontend    serving
✓ Platform         all systems operational
============================================
Setup complete. Your platform is ready.
Access it at: http://ms-s1.tail-xxxx.ts.net
============================================
```

Note the URL shown — this is your platform address. Write it down.

---

## PART 6A — DOCKER AND OPEN WEBUI

This part installs Docker and starts the Open WebUI chat interface.
Docker is used for infrastructure services on this platform — it is not needed for day-to-day use once set up.

### Step 24A — Install Docker

```bash
sudo apt install -y docker.io
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker jarvis
```

After running these commands, **log out and log back in** (or restart the terminal) so the group change takes effect.

### Step 24B — Start Open WebUI

Open WebUI is the AI chat interface. It connects to Ollama automatically.

```bash
docker run -d \
  --name open-webui \
  --restart always \
  -p 3000:8080 \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  ghcr.io/open-webui/open-webui:main
```

This command:
1. Downloads Open WebUI (about 1-2GB, takes a few minutes)
2. Starts it on port 3000
3. Connects it to your local Ollama models
4. Configures it to restart automatically when the mini PC reboots

To check it is running:
```bash
docker ps
```
You should see `open-webui` in the list with status `Up`.

Open WebUI will be accessible at `http://localhost:3000` on the mini PC, and at `your-tailscale-url/chat` from any device once Caddy is configured.

### Step 24C — Configure Caddy for Open WebUI

Add the chat route to your Caddyfile:

```bash
sudo nano /etc/caddy/Caddyfile
```

Add inside your server block:
```
handle /chat* {
    reverse_proxy localhost:3000
}
```

Reload Caddy:
```bash
sudo systemctl reload caddy
```

---

## PART 7 — CONNECT FROM YOUR PHONE

### Step 24 — Install Tailscale on your phone

1. On your iPhone: search for **Tailscale** in the App Store and install it
   On your Android: search for **Tailscale** in the Play Store and install it
2. Open Tailscale on your phone
3. Log in with the same account you used in Step 21
4. Tailscale will ask for VPN permission — allow it
5. Make sure Tailscale is turned on (toggle at the top should be blue/on)

### Step 25 — Access your platform

1. Open the browser on your phone (Safari or Chrome)
2. Type the URL from Step 23 into the address bar
   It looks like: `http://ms-s1.tail-xxxx.ts.net`
3. You should see the platform — starting with the admin panel

If you see the admin panel, everything is working. Your mini PC is now your personal AI server,
accessible from your phone anywhere in the world as long as Tailscale is running on both devices.

---

## PART 8 — UNDERSTANDING YOUR SETUP

Now that everything is running, here is what you have and how to think about it.

### What is running on the mini PC

All of these start automatically when the mini PC turns on:

| What | What it does |
|---|---|
| Tailscale | Lets you connect remotely and securely |
| Caddy | Routes your browser to the right app |
| Ollama | Serves the AI models |
| Docker | Runs infrastructure services (Open WebUI, per-user trading) |
| Open WebUI | AI chat interface (accessible at /chat) |
| Platform services | The individual apps (autocoder, writer, trading, etc.) |

### The apps you can access

From any device with Tailscale installed, open your browser and go to:

| Address | What you get |
|---|---|
| `your-url/admin` | Admin panel — manage everything |
| `your-url/chat` | Simple AI chat |
| `your-url/writer` | Long-form writing assistant |
| `your-url/coding` | Personal coding assistant |
| `your-url/autocoder` | Autonomous development system |

### What the admin panel lets you do

The admin panel is your control centre. From here you can:
- See if all services are running
- Download new AI models
- Create new AI agents
- Add new apps to the platform
- Check system resources
- Apply system updates safely

You should rarely need the terminal after the initial setup.

---

## PART 9 — EVERYDAY USE

### Turning the mini PC off and on

The mini PC is designed to stay on permanently. You do not need to turn it off.

If you want to restart it (for example after a system update):
1. Click the top-right icons on the Ubuntu desktop
2. Click the power icon
3. Click **Restart**

Or from the terminal:
```bash
sudo reboot
```

If the power is cut and restored, the mini PC will turn itself back on automatically (you configured this in the BIOS).

### Checking if everything is running

Open the admin panel at `your-url/admin`. The Dashboard view shows the status of all services.
Green means running. Red means there is a problem.

Or run the validation script from the terminal at any time:
```bash
/opt/platform/scripts/validate-platform.py
```

### Applying system updates

**Never apply updates while the autocoder is running an overnight session.**

To apply updates safely:
1. Open the admin panel
2. Go to the **Updates** section
3. If no autocoder session is active, the **Apply Updates** button will be available
4. Click it and wait — the platform will update and restart affected services automatically

### Checking AI model memory usage

The admin panel **Models** section shows:
- Which models are downloaded
- Which models are currently loaded in memory
- How much GPU memory is being used

If you are running low on memory, you can unload models that are not currently needed.

---

## PART 10 — TROUBLESHOOTING

### The mini PC does not boot from the USB stick

- Make sure the USB stick is properly plugged in
- Go back into the BIOS (Step 5) and check the boot order (Step 6, Setting 4)
- Try a different USB port
- Try recreating the USB stick with Rufus

### The terminal shows errors during setup

Take a photo or screenshot of the error. Common causes:
- **No internet connection** — check your ethernet cable or WiFi
- **Disk full** — unlikely on a fresh install, but check available space with: `df -h`
- **Command not found** — the previous step may not have completed. Scroll up to find where it stopped.

To see what went wrong and try running the setup script again:
```bash
bash /opt/platform/scripts/setup.sh
```

The script is designed to be run multiple times safely — it skips things that are already done.

### I cannot reach the platform from my phone

Check in order:
1. Is Tailscale turned on on your phone? (Check the Tailscale app — toggle should be on)
2. Is Tailscale running on the mini PC? In the terminal: `sudo tailscale status`
   You should see your phone listed as a connected device
3. Is Caddy running? In the terminal: `sudo systemctl status caddy`
   It should say `active (running)`
4. Try the validation script: `/opt/platform/scripts/validate-platform.py`

### An app is not loading

1. Open the admin panel at `your-url/admin`
2. Go to **Apps** or **Dashboard**
3. Find the app that is not loading — if it shows red, click **Restart**
4. Wait 10 seconds and try again

Or from the terminal (replace `platform-chat` with the relevant service name):
```bash
sudo systemctl restart platform-chat
sudo systemctl status platform-chat
```

### Ollama is not responding

```bash
sudo systemctl restart ollama
sudo systemctl status ollama
```

Wait 30 seconds after restarting before trying again — Ollama takes a moment to fully start.

### A model download failed partway through

In the terminal:
```bash
ollama pull qwen2.5-coder:32b
```

Replace the model name with whichever one failed. Ollama will resume from where it stopped.

### The mini PC is not turning on after a power cut

- Check the power cable is connected
- Press the power button
- If it still does not turn on: unplug and replug the power cable, wait 10 seconds, press power button
- If the BIOS settings were lost (some mini PCs reset on power cut): go back to Part 2 and redo the BIOS settings

### I forgot my password

Restart the mini PC and at the login screen click **Not listed?** or your username.
If you truly cannot log in, Ubuntu has a password recovery mode — search for "Ubuntu recovery mode reset password" for current instructions.

### Something else is wrong

Run the validation script and note which checks fail:
```bash
/opt/platform/scripts/validate-platform.py
```

Check the logs for the failing service:
```bash
sudo journalctl -u platform-admin -n 50
```

Replace `platform-admin` with the name of the failing service.
The last 50 lines of the log usually show what went wrong.

---

## REFERENCE — USEFUL TERMINAL COMMANDS

You should rarely need these after setup. Keeping them here for reference.

```bash
# Check if a service is running
sudo systemctl status platform-admin

# Restart a service
sudo systemctl restart platform-admin

# See the last 50 lines of a service's log
sudo journalctl -u platform-admin -n 50

# Follow a service's log live (Ctrl+C to stop)
sudo journalctl -u platform-admin -f

# Check disk space
df -h

# Check memory usage
free -h

# Check Tailscale status
sudo tailscale status

# Restart Caddy (web routing)
sudo systemctl restart caddy

# Restart Ollama (AI models)
sudo systemctl restart ollama

# Reboot the mini PC safely
sudo reboot

# Shut down the mini PC
sudo shutdown now
```

**Service names for reference:**

| Service | Name to use in commands |
|---|---|
| Admin panel | platform-admin |
| Chat app | platform-chat |
| Writer app | platform-writer |
| Coding assistant | platform-coding |
| Autocoder conductor | platform-autocoder-conductor |
| Autocoder RE-agent | platform-autocoder-re-agent |
| Autocoder dashboard | platform-autocoder-dashboard |
| Health monitor | platform-health-monitor |
| ChromaDB | platform-chromadb |
| Ollama | ollama |
| Caddy | caddy |
| Tailscale | tailscaled |

---

## YOU ARE DONE

If you followed every step and the validation passed, your platform is fully operational.

From here, everything happens through the web interface — the admin panel, the apps, the autocoder.
The terminal stays in the background as a safety net you will rarely need.

Welcome to your personal AI platform.
