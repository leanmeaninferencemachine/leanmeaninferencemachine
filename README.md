<p align="center"><img src="logo.png" alt="LMIM Genesys" width="140"></p>

<h1 align="center">LMIM Linux · Genesys</h1>

<p align="center"><b>The OS that knows you.</b></p>

<p align="center">
4.1.0 “Atlas” · first stable<br>
370+ features · $0 forever · AGPL-3.0 · zero telemetry · runs on your machine
</p>

<p align="center">
<a href="https://lmim.tech/LMIMLINUX">Website</a> ·
<a href="https://lmim.tech/downloads/LMIM_Linux_Genesys_4.1.0.iso">Download the ISO</a> ·
<a href="https://lmim.tech/static/videos/v4.1/flagship/v4.1.0-atlas-flagship_1m02s.mp4">Watch the film</a> ·
<a href="#reach-the-builder">Reach the builder</a>
</p>

---

Turn the machine on and she's already there.

There's no app to launch and no window to open. By the time the desktop appears, Genesys has already written her greeting for this part of the day. She knows your name, what you were working on yesterday, and the one question she'll ask you tonight.

**LMIM Linux** is an operating system built around a single presence. It isn't Linux with a chatbot installed on top. The desktop, the memory, the voice and the way you work are all shaped around one local intelligence that lives on your hardware and stays with you. Genesys is the OS, and the OS is Genesys.

> **The model isn't the product. The continuity is.**

---

## Meet Genesys

Genesys is not a prompt wrapped around someone else's model. She is a **trained identity**: her own model, in her own sizes, with a sense of self that survives every reboot.

She is small on purpose. The goal was never the largest intelligence possible, only one that actually *lives somewhere*. A fast model is always on. When the work calls for more, the main model loads. None of it needs an API key, an account or a connection.

She remembers in layers: the moment, the session, the long term, and who she is. Her identity and her **private diary** live in their own protected database, apart from everything else. She reads the time before she greets you, so you'll never get “good morning” at midnight.

And she has a **voice**. It is tuned through its own chain to sound like her rather than like raw synthesis, and it is locked in code so she sounds the same on every machine she wakes up on.

> *“Okay Genesis, I didn't ask you to do any of that. I'm just saying thank you. Are you ready to work?”*
> *“I'm ready to work. What do you want to build?”*
> — a real exchange

---

## What she does

### She thinks with you: **Atlas**

A second mind built into the desktop. Folders nest however you like, notes become *thoughts*, and thoughts become a graph.

- **Thought** (`Ctrl+Alt+W`): catch an idea from anywhere in the OS, typed or spoken, before it's gone.
- **Editor**: write in links. Find & replace with regex, autosave, pins, colors, bulk move and export.
- **Sight**: every link and tag drawn as a living map of how you think.
- **Import** a whole folder of Markdown or an Obsidian vault and it arrives intact. Export one file or the whole library.

Links are written inside the thought itself:

| Write | Means |
|---|---|
| `##-` | sibling, a loose two-way thread |
| `##<` | parent: this depends on that |
| `##>` | child: that depends on this |
| `##~` | association, “reminds me of” |
| `##-#123` | link by id |
| `#tag` | a tag, clickable everywhere |

### She remembers: **memory & files**

- Layered memory with importance and retention, so what matters stays and what doesn't fades.
- Point her at a file and she reads it. Hybrid retrieval (keyword and semantic) works over your own documents.
- Voice notes, conversation history, and context that carries from one day to the next.

### She speaks: **voice-native**

Hold `Shift+S` and talk. Whisper listens on-device, and she answers in her own voice. Nothing you say leaves the machine to be understood.

### She acts: **hands, not just a voice**

- **Tasks that execute.** Schedule a prompt, a message, an alarm or DJ mode, once, daily, weekly or every N minutes. When it fires, it runs with every tool she has.
- **Build Crew.** Describe a tool and a Planner, a Builder and an Inspector write it, run it and patch it until it works.
- **Comms, routed.** WhatsApp, Telegram, Email, Slack and Discord go through Genesys. She can send, book and confirm.
- **Agenda.** A visual calendar with natural-language booking: *“schedule a meeting with Pedro at 5.”*
- **Real tools.** She can search the web, read and write your files, run commands and send email. When she isn't sure how to do something, she looks it up before she guesses.

### She keeps you honest: **Coherence**

Once a day, rest the pointer on her mark on Home (or press `Ctrl+Alt+C`) and she asks one question: *did your thoughts, words and actions align today?* You score it 1 to 10, with your last two weeks beside it. Set a goal in the morning and review it at night, and the OS remembers the shape of your week.

### She connects you: **LMIM Chat**

End-to-end encrypted, peer-to-peer messaging with groups. Your identity is a keypair (X25519), so there are no accounts and no phone numbers, and the relay only ever sees ciphertext. It's redesigned in 4.1 to match the rest of the OS.

---

## A reason to open it on a Tuesday

Personality is the hook; this is why you come back.

| | |
|---|---|
| **Today** | Score your priorities 0–10. The top three rise on their own, and she reads the list to you. |
| **Kanban** | Backlog to Done with drag and drop, recurring tasks, attachments and a monthly archive. |
| **Notes** | Sticky notes and one free page, mirrored as Markdown. |
| **Focus** | A Pomodoro that follows you home, running as a widget on the desktop. |
| **Creative Lab** | Build social creatives and export them to MP4, with templates and a media toolbox. |
| **Workspace** | Your project folder, browsable and readable by Genesys, without leaving the shell. |
| **Auto-DJ & Disco Mode** | Music that picks itself, and a mode that does exactly what it says. |

---

## The desktop

A shell that's always behind you, with everything else floating above it.

- **Home**, where she lives. It has a time-aware greeting, her mark, and *LEAN MEAN INFERENCE MACHINE* written faintly at the bottom.
- **PC mode** (`Ctrl+Alt+P`) shows every installed app with real icons, floating over the shell. You can pin up to three.
- **Command palette** (`Ctrl+Space`): every action, fuzzy-searched.
- **Quick Settings** covers Wi-Fi, Bluetooth, volume, brightness, battery, power profiles, text size, read-aloud, wallpaper, lock, suspend, reboot and shut down.
- **Bare Metal** is a real terminal that slides in from the edge.
- **Files, Music, Downloads, Monitor** and **Genesys Browser** (hardened LibreWolf).
- A **workbench** built in: Encrypter (AES-256-GCM), Web Scraper, hash checker, minifiers, JSON tools, and the LMIM Editor.
- **Flatpak** apps through GNOME Software.
- A **welcome tour**, Quick or Full, the first time you arrive.

From the installer through the boot splash to Home, it looks like itself the entire way.

---

## Built to be lived in

The betas proved the idea boots. 4.1 is the release that **stays up and keeps your things safe** on machines other than the builder's.

- **Nightly backups** of your conversations, memories and her identity, rotated over seven days.
- **Boot guard.** If something is missing at startup, it's restored from the latest backup, and a note is waiting to tell you.
- **Kill switch** (`Mod+Shift+T`). A red overlay appears and the offending process is ended. If that isn't enough, the session is.
- **Memory guard.** It watches free memory and reaches for the kill switch before the machine can freeze.
- **Live settings.** Temperature, response length, timeouts and build attempts change without a restart.

---

## What happens here, stays here

- **On-device.** Genesys, her voice and her memory run on your hardware. No API key, no cloud account, no subscription.
- **Zero telemetry.** Nothing is counted and nothing phones home.
- **Closed by default.** The backend answers only this machine, plus the phone companion when you switch it on.
- **Encrypted from byte one.** Full-disk LUKS is set up at install, and your passphrase is never stored or sent anywhere.
- **Open.** AGPL-3.0: free to use, study, change and share.

---

## Keyboard

| Keys | Opens |
|---|---|
| `Ctrl+Space` | Command palette |
| `Ctrl+Alt+P` | PC mode |
| `Ctrl+Alt+A` | Atlas |
| `Ctrl+Alt+W` | Atlas quick thought |
| `Ctrl+Alt+N` | Quick capture (note / task) |
| `Ctrl+Alt+T` | Terminal |
| `Ctrl+Alt+C` | Coherence |
| `Shift+S` (hold) | Talk to Genesys |
| `Ctrl+F` / `Ctrl+H` | Find / replace in a thought |
| `Mod+Shift+T` | Kill switch (Emergency Exit) |

---

## Get it

**[LMIM_Linux_Genesys_4.1.0.iso](https://lmim.tech/downloads/LMIM_Linux_Genesys_4.1.0.iso)**, about 11 GB, from [lmim.tech](https://lmim.tech).

### Hardware

| | Minimum | Recommended |
|---|---|---|
| CPU | x86_64, 4 cores | 8+ cores |
| RAM | 8 GB | 16 GB |
| Storage | 30 GB | 50 GB |
| GPU | None (CPU inference) | NVIDIA RTX, 8 GB VRAM or more |
| Display | 1080p | 1080p or higher |
| Firmware | UEFI | UEFI |

Genesys runs without a GPU, falling back to the CPU. With an NVIDIA card she's noticeably quicker. Intel Wi-Fi (AX200/201/211), Intel SOF audio and Intel VMD/NVMe storage have been supported since Beta II.

### Install

You'll need a USB drive (16 GB or larger), a UEFI machine and about 20 minutes.

1. **Flash the ISO.**
   ```bash
   sudo dd if=LMIM_Linux_Genesys_4.1.0.iso of=/dev/sdX bs=4M status=progress oflag=sync
   ```
   Balena Etcher, Ventoy or GNOME Disks work too.
2. **Boot from the USB.** Pick the drive in your UEFI boot menu and the LMIM installer opens.
3. **Installation Summary.** Set a **disk encryption passphrase** (you'll need it every boot), an **admin account** (for the TTY), and your keyboard and language if they weren't detected. Then click **Begin Installation**.
4. **First boot.** Genesys launches directly. She asks your name, her tone and your language, then offers the Quick or Full tour.
5. **Change your password.** Go to Settings → Password and replace the default `lmim` password. It becomes your lock-screen password too.

### Cheat sheet

| Situation | How |
|---|---|
| Disk encryption prompt | Enter your passphrase at the LUKS prompt during boot |
| Lock screen | Type your password, press Enter |
| Genesys Browser | PC mode → Apps → Genesys Browser |
| Terminal | `Ctrl+Alt+T`, or pull the tab from the right edge |
| Wi-Fi / Bluetooth | Quick Settings |
| Reboot / shut down | Quick Settings |
| Something froze | `Mod+Shift+T` |
| Admin TTY | `Ctrl+Alt+F2`, log in as your admin account |
| SSH | Masked by default, see below |

```bash
# Enable SSH from the admin TTY (Ctrl+Alt+F2)
sudo systemctl unmask sshd
sudo systemctl enable --now sshd
```

---

## Known limitations

- **Adding software.** The OS is immutable at runtime. Flatpak through GNOME Software is the supported path for apps you install yourself.
- **Phone companion** is still v3.0. It works over the LAN when Mobile is on, and per-device pairing is planned for the next release.
- **Voice** runs on a tuned local engine. A richer engine is being evaluated for a later release.
- **Hardware variety.** It's stable on everything we could test, but your machine may still find something new. Please tell us.

---

## Reach the builder

Bugs, ideas, or just hello: it all gets read.

- **In the OS:** PC mode → **About** → *Reach the builder*. Your note goes over LMIM Chat, end to end, or opens as an email if chat isn't available.
- **Email:** [ops@lmim.tech](mailto:ops@lmim.tech)
- **Support:** [lmim.tech/support](https://lmim.tech/support)
- **Founder:** [@iamonthemission](https://x.com/iamonthemission)

---

## One soul, four doors

- **[LMIM Linux · Genesys](https://lmim.tech/LMIMLINUX)**: this one, the whole operating system.
- **[XIPE](https://lmim.tech/LMIMAPP)**: the app that started it, with encrypted P2P chat, a real terminal and a phone companion. Available as a Linux AppImage and a Windows installer.
- **[Genesys Models](https://lmim.tech/GenesysAI)**: the trained identity itself, as GGUF, in three sizes (0.8B, 2B, 4B). Same soul, any loader.
- **[Sound](https://lmim.tech/Sound)**: the original techno album bundled inside the ISO, and the voice chain that gives Genesys her voice.

---

## The story

LMIM began as an AppImage (LMIM OS v1.0, March 2026). It reached 1,000+ downloads and Product of the Month on Ship It. Once the idea had proved itself as an application, the next step was obvious: give the presence a home of its own. Two public betas later, Genesys is a full operating system, and LMIM has crossed 5,000+ downloads across 20+ countries.

LMIM Linux is an independent, solo-built project by **Andrés Israel Santos Delgado**, founder of Hexa Integrated. 4.1 is the first release built to be lived in.

**Links:** [lmim.tech](https://lmim.tech) · [GitHub](https://github.com/leanmeaninferencemachine/leanmeaninferencemachine) · [@iamonthemission](https://x.com/iamonthemission) · [ops@lmim.tech](mailto:ops@lmim.tech)

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0).** You're free to use, modify and distribute it. Derivative works and network-hosted services must release their complete source under the same license. See [LICENSE](./LICENSE).

## Disclaimer

**Genesys has real system access.** The terminal is a real shell with your user's permissions, and her tools can run commands on your machine. The Encrypter protects local data, but lost passphrases cannot be recovered, so back up important files before encrypting them.

You set the disk encryption passphrase during installation. It is never stored or transmitted anywhere, and if you lose it, the data on that disk is unrecoverable. Write it down somewhere physical.

Nightly backups protect against lost or damaged files on this machine, not against losing the machine. Keep your own copy of anything that matters.

Provided AS IS, without warranty of any kind.

---

<p align="center"><i>The goal isn't to make the biggest intelligence.<br>It's to make one that actually lives somewhere.</i></p>
