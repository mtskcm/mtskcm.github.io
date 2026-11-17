"""Obnoví zhliadnutia/lajky/komentáre v panel/index.html (YouTube, Instagram, Facebook) – spúšťa GitHub Actions (tlačidlo v paneli).
Tokeny len zo secretu PANEL_TOKENS (JSON): {"yt": {client_id, client_secret, refresh_token}, "meta": {<klient>: {pageId, pageToken, igUserId}}}.
TikTok tu nie je (nemá API) – ostáva z posledného zostavenia na Macu."""
import datetime as dt, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Bratislava')
P = 'panel/index.html'
T = json.loads(os.environ['PANEL_TOKENS'])
G = 'https://graph.facebook.com/v23.0'
YT = 'https://www.googleapis.com/youtube/v3'


def call(url, params=None, data=None):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None)
    for a in range(3):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            return {'_error': e.code}
        except Exception:
            time.sleep(4 * (a + 1))
    return {'_error': 0}


src = open(P, encoding='utf-8').read()
i = src.index('const D = ') + len('const D = ')
D, n = json.JSONDecoder().raw_decode(src[i:])
today = dt.date.today().isoformat()
stat = {}


def upd(v, **kw):
    ch = False
    for k, x in kw.items():
        if x is not None and v.get(k) != x:
            v[k] = x
            ch = True
    if ch:
        v['updated'] = today
    p = v['platform']
    stat.setdefault(p, [0, 0])
    stat[p][0] += 1
    stat[p][1] += ch


# YouTube – verejné štatistiky podľa ID videa
yt = [v for c in D['clients'] for v in c['videos'] if v['platform'] == 'youtube']
if yt and T.get('yt'):
    tok = call('https://oauth2.googleapis.com/token', data={**{k: T['yt'][k] for k in ('client_id', 'client_secret', 'refresh_token')}, 'grant_type': 'refresh_token'})
    if 'access_token' in tok:
        ids = sorted({v['video_id'] for v in yt})
        S = {}
        for k in range(0, len(ids), 50):
            j = call(f'{YT}/videos', {'part': 'statistics', 'id': ','.join(ids[k:k + 50]), 'access_token': tok['access_token']})
            for it in j.get('items', []):
                S[it['id']] = it.get('statistics', {})
        for v in yt:
            s = S.get(v['video_id'])
            if s:
                upd(v, views=int(s.get('viewCount', 0)), likes=int(s.get('likeCount', 0)), comments=int(s.get('commentCount', 0)))
    else:
        print('YouTube: prihlásenie zlyhalo', tok.get('_error'))

for c in D['clients']:
    m = T.get('meta', {}).get(c['id'])
    if not m:
        continue
    t = m['pageToken']
    # Instagram
    for v in [v for v in c['videos'] if v['platform'] == 'instagram']:
        b = call(f"{G}/{v['video_id']}", {'fields': 'like_count,comments_count', 'access_token': t})
        ins = call(f"{G}/{v['video_id']}/insights", {'metric': 'views,reach', 'access_token': t})
        x = {d['name']: (d.get('values') or [{}])[0].get('value') for d in ins.get('data', [])}
        upd(v, views=x.get('views'), reach=x.get('reach'), likes=b.get('like_count'), comments=b.get('comments_count'))
    # Facebook – video_id v paneli je ID príspevku; ID videa (pre insights) z /video_reels
    fb = [v for v in c['videos'] if v['platform'] == 'facebook']
    if not fb:
        continue
    vid, after = {}, None
    for _ in range(6):
        j = call(f"{G}/{m['pageId']}/video_reels", {'fields': 'id,post_id', 'limit': 50, 'access_token': t, **({'after': after} if after else {})})
        for r in j.get('data', []):
            vid[r.get('post_id') or r['id']] = r['id']
        after = j.get('paging', {}).get('cursors', {}).get('after')
        if not after or not j.get('paging', {}).get('next'):
            break
    for v in fb:
        e = call(f"{G}/{v['video_id']}", {'fields': 'reactions.summary(total_count).limit(0),comments.summary(total_count).limit(0),shares', 'access_token': t})
        kw = {}
        if '_error' not in e:
            kw = {'likes': e.get('reactions', {}).get('summary', {}).get('total_count'),
                  'comments': e.get('comments', {}).get('summary', {}).get('total_count'), 'shares': e.get('shares', {}).get('count', 0)}
        if v['video_id'] in vid:
            ins = call(f"{G}/{vid[v['video_id']]}/video_insights", {'access_token': t})
            x = {d['name']: (d.get('values') or [{}])[0].get('value') for d in ins.get('data', [])}
            kw.update(views=x.get('blue_reels_play_count'), reach=x.get('post_impressions_unique'))
        upd(v, **kw)

D['views_refreshed'] = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
blob = json.dumps(D, ensure_ascii=False).replace('</', '<\\/')
open(P, 'w', encoding='utf-8').write(src[:i] + blob + src[i + n:])
for p, (a, b) in sorted(stat.items()):
    print(f'{p:10} {a:4} videí, zmenených {b}')
