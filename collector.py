#!/usr/bin/env python3
"""VRChatの話題を無料ソースから集めて public/index.html を作る。
ソース: Misskey.io(写真・タグ)、BOOTH(衣装)、Reddit r/VRChat(海外の話題)
APIキー不要。失敗したソースは飛ばして続行します。"""
import json, re, html, os, urllib.request, urllib.parse, collections, datetime
import xml.etree.ElementTree as ET

UA = "vrc-topics-digest/0.1 (personal use, low frequency)"
E = html.escape


def fetch(url, body=None):
    h = {"User-Agent": UA}
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, body, h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def misskey(tag, files=False):
    try:
        b = json.dumps({"tag": tag, "limit": 100, "withFiles": files}).encode()
        return json.loads(fetch("https://misskey.io/api/notes/search-by-tag", b))
    except Exception as e:
        print("Misskey NG:", e)
        return []


def score(n):
    return sum((n.get("reactions") or {}).values()) + n.get("renoteCount", 0)


def photos():
    out = []
    for n in misskey("VRChat", True):
        for f in n.get("files", []):
            if f.get("type", "").startswith("image/") and not f.get("isSensitive"):
                out.append((score(n), f.get("thumbnailUrl") or f["url"],
                            "https://misskey.io/notes/" + n["id"], (n.get("text") or "")[:60]))
                break
    return sorted(out, reverse=True)[:24]


def interests():
    c = collections.Counter()
    for n in misskey("VRChat"):
        for t in set(n.get("tags") or []):
            if "vrchat" not in t.lower():
                c[t] += 1
    return c.most_common(20)


def outfits():
    try:
        page = fetch("https://booth.pm/ja/search/VRChat%20%E8%A1%A3%E8%A3%85?sort=wish_lists")
        items = []
        for m in re.finditer(r'<li[^>]+data-product-id="(\d+)"[^>]*>', page):
            name = re.search(r'data-product-name="([^"]*)"', m.group(0))
            img = re.search(r'data-original="([^"]+)"', page[m.end():m.end() + 3000])
            items.append((html.unescape(name.group(1)) if name else m.group(1),
                          "https://booth.pm/ja/items/" + m.group(1), img.group(1) if img else ""))
        return items[:16]
    except Exception as e:
        print("BOOTH NG:", e)
        return []


def reddit():
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(fetch("https://www.reddit.com/r/VRChat/top/.rss?t=week"))
        return [(e.find("a:title", ns).text, e.find("a:link", ns).get("href"))
                for e in root.findall("a:entry", ns)][:10]
    except Exception as e:
        print("Reddit NG:", e)
        return []


def x_links():
    """Xは無料で自動取得できないため、日付入りの検索リンクを毎回作る(クリックでX上の結果が開く)"""
    since = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()
    base = f"lang:ja -filter:replies since:{since}"
    qs = [
        ("今週の人気投稿(全体)", f"#VRChat min_faves:200 {base}"),
        ("衣装・改変の話題", f"VRChat (衣装 OR 改変 OR 対応アバター) min_faves:50 {base}"),
        ("新作衣装(BOOTH)", f"VRChat booth.pm (衣装 OR 新作) min_faves:30 {base}"),
        ("話題の写真", f"#VRChat filter:images min_faves:300 {base}"),
        ("ワールド紹介", f"#VRChat_world紹介 min_faves:50 {base}"),
        ("イベント・告知", f"(#VRChatイベント OR VRChatイベント) min_faves:30 {base}"),
    ]
    rows = ""
    for name, q in qs:
        u = "https://x.com/search?src=typed_query&q=" + urllib.parse.quote(q)
        rows += (f'<div class="xrow"><span>{E(name)}</span>'
                 f'<a class="chip" href="{E(u)}&f=top" target="_blank" rel="noopener">人気</a>'
                 f'<a class="chip" href="{E(u)}&f=live" target="_blank" rel="noopener">最新</a></div>')
    return rows


def bluesky():
    """任意: 環境変数 BSKY_HANDLE / BSKY_APP_PASSWORD があれば日本語の人気投稿を取る(無料)"""
    h, p = os.environ.get("BSKY_HANDLE"), os.environ.get("BSKY_APP_PASSWORD")
    if not (h and p):
        return []
    try:
        sess = json.loads(fetch("https://bsky.social/xrpc/com.atproto.server.createSession",
                                json.dumps({"identifier": h, "password": p}).encode()))
        req = urllib.request.Request(
            "https://bsky.social/xrpc/app.bsky.feed.searchPosts?q=VRChat&lang=ja&sort=top&limit=30",
            headers={"User-Agent": UA, "Authorization": "Bearer " + sess["accessJwt"]})
        posts = json.load(urllib.request.urlopen(req, timeout=30))["posts"]
        out = []
        for x in posts:
            imgs = (x.get("embed") or {}).get("images") or []
            out.append((x.get("likeCount", 0) + x.get("repostCount", 0),
                        imgs[0]["thumb"] if imgs else "",
                        f"https://bsky.app/profile/{x['author']['handle']}/post/{x['uri'].split('/')[-1]}",
                        (x.get("record", {}).get("text") or "")[:60]))
        return sorted(out, reverse=True)[:18]
    except Exception as e:
        print("Bluesky NG:", e)
        return []


def grok_notes():
    """grok.txt(Grokで調べた結果を貼ったメモ)を読み、リンク付きで表示用HTMLにする"""
    try:
        txt = open("grok.txt", encoding="utf-8").read()
    except OSError:
        return ""
    def link(t):
        return re.sub(r"(https?://[^\s<>]+)", r'<a href="\1" target="_blank" rel="noopener">\1</a>', E(t))
    out = []
    for ln in txt.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith("## "):
            out.append(f"<h3>{E(ln[3:])}</h3>")
        elif ln.startswith("- "):
            out.append(f"<p>・{link(ln[2:])}</p>")
        else:
            out.append(f"<p>{link(ln)}</p>")
    return "".join(out)


def card(img, href, title, sub=""):
    im = f'<img src="{E(img)}" loading="lazy" referrerpolicy="no-referrer" alt="">' if img else ""
    return (f'<a class="card" href="{E(href)}" target="_blank" rel="noopener">'
            f'{im}<span>{E(title)}</span><small>{E(sub)}</small></a>')


def section(title, body, note=""):
    body = body or "<p class='empty'>今回は取得できませんでした</p>"
    return f"<section><h2>{E(title)}</h2><p class='note'>{E(note)}</p>{body}</section>"


def render(ph, it, of, rd, bs=(), gk=""):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    s1 = section("話題の衣装", "".join(card(i, u, n) for n, u, i in of) and
                 '<div class="grid">' + "".join(card(i, u, n) for n, u, i in of) + "</div>",
                 "BOOTHの検索結果(人気順を指定)")
    chips = "".join(
        f'<a class="chip" href="https://misskey.io/tags/{E(t)}" target="_blank" rel="noopener">#{E(t)} <b>{c}</b></a>'
        for t, c in it)
    rl = "".join(f'<li><a href="{E(u)}" target="_blank" rel="noopener">{E(t)}</a></li>' for t, u in rd)
    s2 = section("興味関心", (f'<div class="chips">{chips}</div>' if chips else "") +
                 (f"<h3>海外の週間人気(Reddit)</h3><ul>{rl}</ul>" if rl else ""),
                 "最近のVRChat投稿に一緒に付いていたタグの数")
    s3 = section("話題の写真", ('<div class="grid">' + "".join(
        card(i, u, t or "投稿を見る", f"♥ {s}") for s, i, u, t in ph) + "</div>") if ph else "",
                 "Misskey.ioの投稿(反応数順)。画像の権利は投稿者にあります。リンク先でご覧ください")
    sx = section("X(日本語)の話題をひらく", '<div class="xl">' + x_links() + "</div>",
                 "Xは無料で自動取得できないため、直近7日・日本語・いいね数で絞った検索リンクです。押すとXで開きます")
    s4 = section("Bluesky(日本語)の人気投稿", ('<div class="grid">' + "".join(
        card(i, u, t or "投稿を見る", f"♥ {sc}") for sc, i, u, t in bs) + "</div>") if bs else "",
                 "Blueskyのアカウント設定をした場合のみ表示")
    s5 = section("Grokで調べたXの話題", gk or "<p class='empty'>grok.txt を作ると、ここに表示されます</p>",
                 "Grokの回答を grok.txt に貼ると反映されます。リンク先で内容を確認してください")
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>VRChat話題まとめ</title>
<style>:root{{--bg:#fff;--fg:#1a1a1a;--sub:#666;--cd:#f3f3f6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#eee;--sub:#aaa;--cd:#24242b}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font-family:system-ui,sans-serif;max-width:1000px;margin:auto}}
h2{{border-left:5px solid #7c5cff;padding-left:8px}}.note,small{{color:var(--sub);font-size:.8rem}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
.card{{background:var(--cd);border-radius:10px;overflow:hidden;color:inherit;text-decoration:none;display:flex;flex-direction:column;gap:4px;padding-bottom:8px}}
.card img{{width:100%;aspect-ratio:1;object-fit:cover}}.card span,.card small{{padding:0 8px;font-size:.85rem}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}}.chip{{background:var(--cd);padding:6px 12px;border-radius:99px;color:inherit;text-decoration:none}}
.empty{{color:var(--sub)}}.xrow{{display:flex;gap:8px;align-items:center;margin:6px 0}}.xrow span{{flex:1}}</style></head><body>
<h1>VRChat話題まとめ</h1><p class="note">更新: {now:%Y-%m-%d %H:%M} JST</p>{sx}{s5}{s1}{s2}{s3}{s4}</body></html>"""


if __name__ == "__main__":
    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8") as f:
        f.write(render(photos(), interests(), outfits(), reddit(), bluesky(), grok_notes()))
    print("public/index.html を作成しました")
