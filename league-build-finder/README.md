# Jam's League Builds

Pick a **role**, a **champion**, a **region** and a **patch**, click **Search**, and it shows what Platinum+ ranked solo queue players build on that champion:

- **Runes**: keystone, primary and secondary runes, stat shards
- **Item build in purchase order**: starting items, the 3 core items in the order they're bought, then the most-bought 4th, 5th and 6th items
- **First item: what to buy first**: the components of your first major item (boots skipped), in the order to buy them, with the smaller pieces to buy if you can't afford a whole component
- Summoner spells, skill order, and the other popular choices for items 4-6

Runs locally on your PC in your browser. Nothing to log in to.

## How to download and launch

1. Double-click **`build_exe.bat`** (needs Python on your PC, only for this step). It takes about a minute.
2. You get **`Jam's League Builds.exe`** in this folder. That one file is the whole app: friends don't need Python or anything else. Windows 10/11 already has the Edge engine it uses for its window.
3. Double-click it to run. Right-click it > **Pin to Start** or **Pin to taskbar** if you like.

The .exe keeps its downloaded data in `%LOCALAPPDATA%\JamsLeagueBuilds`, so it can live anywhere (Desktop, Downloads...). An optional `settings.json` placed next to the .exe is picked up too.

## Using it

Choose Role, then Champion (the list only shows champions actually played in that role; tick **List every champion** to see them all), then Region and Patch, and click **Search**.

## What a search shows

- **Starting / Boots / First back** strip: starting items; boots (usual pick first, then common swaps); and the pieces of your first item in the order to buy them.
- **Main Build** tab: a flow chart. the **3 core items** in buy order, then the best next item for each enemy type.
- **Situational** tab: items 4+ depend on the game, so instead of a fixed list there are 3 groups:
  - **vs Healing & Shields**: Grievous Wounds items
  - **vs Tanks**: penetration and max-health damage
  - **vs Burst & Assassins**: survival items (stasis, spell shields, revives, lifelines)
  Each group uses the items this champion's Platinum+ players actually buy later on (with their win rate), sorted by what the item does. If the champion has no common pick for a group, it shows a standard option for that build type (AP, AD or tank), marked as such.
- **The Runes**: both full rune trees with the chosen runes lit up, the stat shards, and a short note on the keystone.
- **Spells & Skill Order**: summoner spells, which ability to max first, and a level 1-18 grid.

## Which build it recommends

The rule applies to the **3 core items** (items 4+ vary too much from game to game). The core is recommended when it:

- **wins more than 50%** of its games,
- appears in **at least 10%** of that champion's games (role, region and patch you picked), and
- has **at least 1,000 games** behind it (so the win rate isn't luck; it's accurate to about ±1.5%).

If it doesn't, the app still shows the **default most played Platinum+ build**, with one yellow note under the champion's name saying so.

u.gg counts boots as one of the first 3 items. When that happens, the app moves boots to the Boots box and adds the most common next item, so you always see 3 real items plus boots.

To use a different rank bracket, change `ugg_rank_key`, `ugg_rank_name` and `rank_label` in `settings.json` (Emerald+ is `16` / `emerald_plus`, Diamond+ is `11` / `diamond_plus`).

The numbers can be changed in `settings.json`: `min_winrate`, `min_pick_share` (0.10 = 10%), `min_build_games`, and `min_situational_games` (fewest games for a champion's own situational pick, default 100).

## Where the data comes from, and its limits

- **Build stats: u.gg**, ranked solo queue, **Platinum+** (Platinum and above). The app reads the same public stats files the u.gg website loads, so results should match u.gg's build page for the same champion/role/rank/region/patch. Each result has a **compare on u.gg** link so you can check.
- **Names, icons, item recipes: Riot's Data Dragon** (official).
- **Region**: NA, EUW, KR, EUNE, BR, LAN, LAS, OCE, RU, TR, JP, or **Any** (all regions combined, which gives the biggest sample).
- **Patch**: the current patch or the previous one. Right after a patch drops, the current one may have little or no data for a day or two; switch to the previous patch.
- **Build order** is the most popular path among Platinum+ players, which on u.gg is also a high-win-rate one. Win rates are shown next to each part so you can judge. Small samples (under 200 games, e.g. a rare pick in a single region) get a warning.
- **First-item components** come from the item's recipe, not from stats: no public site publishes "which component players buy first". The order shown (most expensive piece first, with its cheaper sub-pieces if you're short on gold) is the standard rule for getting the most stats out of your first back.
- u.gg doesn't offer an official API. The files the app reads are public and unauthenticated, but u.gg could change their format at any time. If that happens, searches will show an error or missing sections rather than wrong builds; tell me and I'll update the app.

## Troubleshooting

- **"python is not recognized"**: Python isn't on PATH. Reinstall it with "Add python.exe to PATH" ticked, or use the `winget` command above.
- **Every search says "returned 403" or "Couldn't download build stats"**: first try the previous patch. If every champion fails on both patches, u.gg is blocking the request (their Cloudflare protection) or changed their file version. Open a search's **Technical detail** and send me what it says along with the text in the black window.
- **A champion is missing from a role**: tick **List every champion**. Off-role picks with very few games are hidden by default.
- **Icons don't show**: they load from Riot's servers in your browser; the build still works without them.
- **Clicking the icon does nothing / shows an error box**: the details are in `cache\launcher.log`. Running `start.bat` also shows what's wrong in its window. Send me either.
- **Windows SmartScreen or antivirus asks about the shortcut**: it's just `pythonw.exe` (part of Python) running `launcher.pyw` from this folder.
- **Port 8766 already in use**: the app is probably already open in another window. Otherwise run `py app.py --port 8800` from a terminal in this folder.

## Files

```
app.py              the app (downloads and reads the stats, runs the local web page)
build_exe.bat       builds "Jam's League Builds.exe" (version_info.txt = publisher details)
launcher.pyw        desktop launcher: starts the app with no console and opens its window
install.bat         creates the Desktop and Start Menu icons (uninstall.bat removes them)
icon.ico            the app icon (static/logo.png is the same art for the page)
static/index.html   the web page
settings.json       optional tweaks (port, small-sample warning, cache time)
start.bat           double-click to run
cache/              downloaded data, created automatically (safe to delete)
```
